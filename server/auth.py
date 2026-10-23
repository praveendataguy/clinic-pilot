"""Staff accounts: sign-up requests, approval, roles, login and sessions.

All passwords are stored salted and hashed (scrypt). Session tokens are stored hashed too.
Functions that change things for other people (approve, reject, list) take the caller's
session token and re-check it here, so nothing depends on what the web page claims.
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from mailer import send_email
from permissions import ASSIGNABLE_ROLES, ROLE_LABELS

load_dotenv()

DB_PATH = Path(os.getenv("RECEPTION_DB") or Path(__file__).with_name("reception.db"))
SESSION_HOURS = 8
MAX_FAILS = 5
LOCK_MINUTES = 10
CLINIC = os.getenv("CLINIC_NAME", "Sunrise Family Clinic")
APP_URL = os.getenv("APP_URL", "http://localhost:8501")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
FMT = "%Y-%m-%d %H:%M:%S"


def _now():
    return datetime.now().strftime(FMT)


@contextmanager
def _db():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


# ------------------------------------------------------------------ passwords
def hash_password(password):
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${2 ** 14}$8$1${salt.hex()}${h.hex()}"


def check_password(password, stored):
    try:
        _, n, r, p, salt, h = stored.split("$")
        want = bytes.fromhex(h)
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                             n=int(n), r=int(r), p=int(p), dklen=len(want))
        return hmac.compare_digest(got, want)
    except Exception:
        return False


_DUMMY = None


def _dummy_check(password):
    """Same work for an unknown email, so timing does not reveal which emails exist."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password("not-a-real-password")
    check_password(password, _DUMMY)


def _password_problem(password, email):
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        return "Password must contain letters and numbers."
    if password.lower() == email.lower():
        return "Password cannot be your email."
    return None


# ---------------------------------------------------------------------- setup
def init_auth():
    """Create the tables and the super admin. Safe to call many times."""
    with _db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            role TEXT DEFAULT '', status TEXT DEFAULT 'pending', is_super INTEGER DEFAULT 0,
            failed_logins INTEGER DEFAULT 0, locked_until TEXT, created_at TEXT,
            decided_by INTEGER, decided_at TEXT, last_login TEXT);
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
            created_at TEXT, expires_at TEXT);
        """)
        email = os.getenv("SUPER_ADMIN_EMAIL", "").strip().lower()
        password = os.getenv("SUPER_ADMIN_PASSWORD", "")
        has_super = c.execute("SELECT 1 FROM users WHERE is_super=1").fetchone()
        if has_super:
            return
        if not (email and password):
            print("WARNING: SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD are not set in .env, "
                  "so nobody can approve new accounts.")
            return
        existing = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            c.execute("UPDATE users SET role='super_admin', status='active', is_super=1, "
                      "password_hash=? WHERE id=?", (hash_password(password), existing["id"]))
        else:
            c.execute("INSERT INTO users (name, email, password_hash, role, status, is_super, created_at) "
                      "VALUES (?,?,?,?,?,1,?)",
                      ("Super admin", email, hash_password(password), "super_admin", "active", _now()))
        print(f"Super admin account ready: {email}")


# --------------------------------------------------------------------- sign-up
def signup(name, email, password):
    name = (name or "").strip()
    email = (email or "").strip().lower()
    if not (2 <= len(name) <= 80):
        return {"ok": False, "message": "Please enter your full name."}
    if not EMAIL_RE.match(email):
        return {"ok": False, "message": "Please enter a valid email address."}
    problem = _password_problem(password or "", email)
    if problem:
        return {"ok": False, "message": problem}
    with _db() as c:
        old = c.execute("SELECT status FROM users WHERE email=?", (email,)).fetchone()
        if old:
            msg = {"pending": "A request for this email is already waiting for approval.",
                   "rejected": "A request for this email was not approved. Please contact the clinic owner."}
            return {"ok": False, "message": msg.get(old["status"], "An account with this email already exists. Please log in.")}
        c.execute("INSERT INTO users (name, email, password_hash, status, created_at) VALUES (?,?,?,?,?)",
                  (name, email, hash_password(password), "pending", _now()))
        pending = c.execute("SELECT COUNT(*) FROM users WHERE status='pending'").fetchone()[0]
        owners = [r["email"] for r in c.execute("SELECT email FROM users WHERE is_super=1 AND status='active'")]
    for owner in owners:
        send_email(owner, f"{CLINIC}: new access request from {name}",
                   f"{name} ({email}) has asked for an account.\n\n"
                   f"Open the app and go to Access requests to choose a role and approve or reject it.\n"
                   f"Requests waiting: {pending}\n{APP_URL}\n")
    return {"ok": True, "message": "Request sent. You will get an email when the clinic owner approves your account."}


# ------------------------------------------------------------- login / sessions
def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def login(email, password):
    email = (email or "").strip().lower()
    password = password or ""
    generic = {"ok": False, "error": "Wrong email or password."}
    with _db() as c:
        u = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if u is None:
            _dummy_check(password)
            return generic
        if u["locked_until"] and u["locked_until"] > _now():
            return {"ok": False, "error": f"Too many wrong attempts. Try again in {LOCK_MINUTES} minutes."}
        if not check_password(password, u["password_hash"]):
            fails = (u["failed_logins"] or 0) + 1
            if fails >= MAX_FAILS:
                until = (datetime.now() + timedelta(minutes=LOCK_MINUTES)).strftime(FMT)
                c.execute("UPDATE users SET failed_logins=0, locked_until=? WHERE id=?", (until, u["id"]))
            else:
                c.execute("UPDATE users SET failed_logins=? WHERE id=?", (fails, u["id"]))
            return generic
        # Password is right. Now say why a login might still be refused.
        if u["status"] == "pending":
            return {"ok": False, "error": "Your account is waiting for approval by the clinic owner."}
        if u["status"] == "rejected":
            return {"ok": False, "error": "Your request was not approved. Please contact the clinic owner."}
        if u["status"] != "active":
            return {"ok": False, "error": "This account is switched off. Please contact the clinic owner."}
        token = secrets.token_urlsafe(32)
        expires = (datetime.now() + timedelta(hours=SESSION_HOURS)).strftime(FMT)
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (_now(),))
        c.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                  (_token_hash(token), u["id"], _now(), expires))
        c.execute("UPDATE users SET failed_logins=0, locked_until=NULL, last_login=? WHERE id=?", (_now(), u["id"]))
        return {"ok": True, "token": token,
                "user": {"id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"]}}


def verify_token(token):
    """Return the logged-in user for a session token, or None."""
    if not token:
        return None
    with _db() as c:
        r = c.execute("SELECT u.id, u.name, u.email, u.role, u.status, s.expires_at "
                      "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=?",
                      (_token_hash(token),)).fetchone()
    if r is None or r["expires_at"] < _now() or r["status"] != "active":
        return None
    return {"id": r["id"], "name": r["name"], "email": r["email"], "role": r["role"]}


def logout(token):
    if token:
        with _db() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))


# -------------------------------------------------------- super admin actions
def _super(token):
    u = verify_token(token)
    return u if u and u["role"] == "super_admin" else None


def pending_requests(token):
    if not _super(token):
        return []
    with _db() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, name, email, created_at FROM users WHERE status='pending' ORDER BY id")]


def list_users(token):
    if not _super(token):
        return []
    with _db() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, name, email, role, status, last_login FROM users ORDER BY is_super DESC, id")]


def approve(token, user_id, role):
    actor = _super(token)
    if not actor:
        return {"ok": False, "message": "Only the super admin can approve accounts."}
    if role not in ASSIGNABLE_ROLES:
        return {"ok": False, "message": "Pick a role: viewer, editor or admin."}
    with _db() as c:
        u = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if u is None or u["is_super"] or u["status"] != "pending":
            return {"ok": False, "message": "That request is not waiting for approval."}
        c.execute("UPDATE users SET status='active', role=?, decided_by=?, decided_at=?, failed_logins=0 WHERE id=?",
                  (role, actor["id"], _now(), user_id))
    status = send_email(u["email"], f"Your {CLINIC} account is ready",
                        f"Hello {u['name']},\n\nYour account has been created. Your role is {ROLE_LABELS[role]}.\n\n"
                        f"Please log in here with the email and password you chose:\n{APP_URL}\n\n{CLINIC}\n")
    return {"ok": True, "message": f"Approved {u['name']} as {ROLE_LABELS[role]}. Email: {status}."}


def reject(token, user_id):
    actor = _super(token)
    if not actor:
        return {"ok": False, "message": "Only the super admin can reject accounts."}
    with _db() as c:
        u = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if u is None or u["is_super"] or u["status"] != "pending":
            return {"ok": False, "message": "That request is not waiting for approval."}
        c.execute("UPDATE users SET status='rejected', decided_by=?, decided_at=? WHERE id=?",
                  (actor["id"], _now(), user_id))
    send_email(u["email"], f"Your {CLINIC} access request",
               f"Hello {u['name']},\n\nYour access request was not approved. "
               f"Please contact the clinic owner if you think this is a mistake.\n\n{CLINIC}\n")
    return {"ok": True, "message": f"Rejected {u['name']}."}