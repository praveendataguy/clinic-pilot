"""Chat history + observability log for the Sunrise Clinic receptionist.

Every conversation turn is saved. A turn that went wrong is flagged so the product
owner can see it in "Observability Logs" and improve the product.

Flags:  error      - the assistant crashed or Gemini/the server failed
        tool_error - a tool returned an error or was refused
        unanswered - the reply says it could not help / did not have the information
        escalated  - the caller was handed to a human (the AI could not finish it)
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

DB_PATH = Path(os.environ.get("CHAT_DB") or Path(__file__).resolve().parent.parent / "server" / "chats.db")

FLAG_LABELS = {
    "error": "Error",
    "tool_error": "Tool error",
    "unanswered": "Unanswered",
    "escalated": "Escalated to human",
}
FLAG_ICONS = {"error": "🔴", "tool_error": "🟠", "unanswered": "🟡", "escalated": "🔵"}

_UNANSWERED = (
    "i don't have", "i do not have", "i'm not sure", "i am not sure", "i can't help", "i cannot help",
    "i can't assist", "i cannot assist", "unable to", "i don't know", "i do not know",
    "don't have information", "not able to", "didn't catch", "did not catch", "too many steps",
    "i couldn't find", "i could not find", "outside of what i can", "not something i can",
)
_TOOL_ERR = ("error", "denied", "invalid", "failed", "could not", "couldn't", "not found", "refused")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY, user_email TEXT, user_name TEXT, title TEXT,
            created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id TEXT, role TEXT, text TEXT,
            tools TEXT DEFAULT '[]', ts TEXT, flag TEXT DEFAULT '', reason TEXT DEFAULT '',
            resolved INTEGER DEFAULT 0);
        CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conv_id);
        CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_email, updated_at);
        """)


def new_id():
    return uuid.uuid4().hex[:12]


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def classify(reply, tool_log, error=None):
    """Return (flag, reason); flag is '' when the turn looks fine."""
    if error:
        return "error", f"Exception: {error}"[:300]
    for line in tool_log or []:
        name, _, out = line.partition(" -> ")
        low = out.lower()
        if name.startswith("transfer_to_human"):
            continue
        if any(k in low for k in _TOOL_ERR):
            return "tool_error", f"{name.split('(')[0]}: {out[:200]}"
    if any(line.startswith("transfer_to_human") for line in tool_log or []):
        return "escalated", "The assistant handed the caller to a human."
    low = (reply or "").lower()
    for k in _UNANSWERED:
        if k in low:
            return "unanswered", f'Reply contains "{k}".'
    return "", ""


def save_turn(conv_id, user, question, reply, tool_log, error=None):
    """Store one question + answer. Never raises, so logging can't break the chat."""
    try:
        init()
        flag, reason = classify(reply, tool_log, error)
        now = _now()
        with _conn() as c:
            if not c.execute("SELECT 1 FROM conversations WHERE id=?", (conv_id,)).fetchone():
                title = " ".join(question.split())[:48] or "New chat"
                c.execute("INSERT INTO conversations VALUES (?,?,?,?,?,?)",
                          (conv_id, user["email"], user["name"], title, now, now))
            c.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conv_id))
            c.execute("INSERT INTO messages (conv_id, role, text, ts) VALUES (?,?,?,?)",
                      (conv_id, "user", question, now))
            c.execute("INSERT INTO messages (conv_id, role, text, tools, ts, flag, reason) VALUES (?,?,?,?,?,?,?)",
                      (conv_id, "assistant", reply, json.dumps(tool_log or []), now, flag, reason))
        return flag
    except Exception:
        return ""


def list_conversations(email, limit=30):
    try:
        init()
        with _conn() as c:
            rows = c.execute("SELECT id, title, updated_at FROM conversations WHERE user_email=? "
                             "ORDER BY updated_at DESC LIMIT ?", (email, limit)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def load_conversation(conv_id, email):
    """Messages of one of this user's own conversations as (role, text, tools)."""
    try:
        with _conn() as c:
            if not c.execute("SELECT 1 FROM conversations WHERE id=? AND user_email=?", (conv_id, email)).fetchone():
                return []
            rows = c.execute("SELECT role, text, tools FROM messages WHERE conv_id=? ORDER BY id", (conv_id,)).fetchall()
        return [(r["role"], r["text"], json.loads(r["tools"] or "[]")) for r in rows]
    except Exception:
        return []


def stats():
    try:
        init()
        with _conn() as c:
            total = c.execute("SELECT COUNT(*) FROM messages WHERE role='assistant'").fetchone()[0]
            by = {r["flag"]: r["n"] for r in c.execute(
                "SELECT flag, COUNT(*) n FROM messages WHERE role='assistant' AND flag!='' AND resolved=0 GROUP BY flag")}
        return {"total": total, "open": sum(by.values()), "by_flag": by}
    except Exception:
        return {"total": 0, "open": 0, "by_flag": {}}


def flagged(flag="", include_resolved=False, limit=200):
    """Flagged assistant replies, newest first, each with the question that caused it."""
    try:
        init()
        sql = ("SELECT m.id, m.ts, m.flag, m.reason, m.text AS reply, m.tools, m.resolved, c.user_name, c.user_email, "
               "(SELECT u.text FROM messages u WHERE u.conv_id=m.conv_id AND u.role='user' AND u.id<m.id "
               " ORDER BY u.id DESC LIMIT 1) AS question "
               "FROM messages m JOIN conversations c ON c.id=m.conv_id WHERE m.role='assistant' AND m.flag!=''")
        args = []
        if flag:
            sql += " AND m.flag=?"; args.append(flag)
        if not include_resolved:
            sql += " AND m.resolved=0"
        sql += " ORDER BY m.id DESC LIMIT ?"; args.append(limit)
        with _conn() as c:
            rows = [dict(r) for r in c.execute(sql, args).fetchall()]
        for r in rows:
            r["tools"] = json.loads(r["tools"] or "[]")
        return rows
    except Exception:
        return []


def resolve(message_id, done=True):
    with _conn() as c:
        c.execute("UPDATE messages SET resolved=? WHERE id=?", (1 if done else 0, message_id))