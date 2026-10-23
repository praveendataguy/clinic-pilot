import csv
import os
import sqlite3
from datetime import datetime, time, timedelta
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from doctors import DOCTORS, SPECIALTIES, SPECIALTY_DOCTORS, find_doctor, resolve_specialty
from phone import validate_phone

load_dotenv()

mcp = FastMCP("ai-receptionist", host="127.0.0.1", port=8000)
DB_PATH = Path(__file__).parent / "reception.db"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
STAFF_PIN = os.getenv("STAFF_PIN", "")
DOWNLOADS_DIR = Path.home() / "Downloads"
REPORT_COLUMNS = ["Time", "Patient name", "Country", "Phone", "Email"]

# ---- EDIT THIS: your demo business ----
BUSINESS = {
    "name": "Sunrise Family Clinic",
    "address": "12 Palm Street, Dubai",
    "phone": "+971-4-000-0000",
    "hours": "Monday to Saturday, 09:00 to 18:00. Closed on Sunday.",
}
OPEN_TIME, CLOSE_TIME = time(9, 0), time(18, 0)
CLOSED_WEEKDAYS = {6}          # Monday=0 ... Sunday=6
SLOT_MINUTES = 30
SERVICES = {"general checkup": 30, "consultation": 30, "dental cleaning": 60}
FAQS = {
    "parking": "Free parking is available behind the building.",
    "insurance": "We accept most major insurance plans. Please bring your card.",
    "payment": "We accept cash and all major cards.",
    "cancellation": "Please cancel at least 24 hours before your appointment.",
}
# ---------------------------------------


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

_ORD = {1: "1st", 2: "2nd", 3: "3rd"}


def _default_room(d):
    group, j = divmod(d["id"] - 1, 5)          # 5 doctors per specialty
    floor = 1 + group // 3                      # 3 specialties per floor
    room = f"{floor}{(group % 3) * 5 + j + 1:02d}"
    text = (f"Take the lift to the {_ORD.get(floor, str(floor) + 'th')} floor. "
            f"You will see a signboard with {d['name']}'s name - follow it to Room {room}. "
            f"Have a happy visit!")
    return floor, room, text


def _seed_rooms(c):
    c.execute("CREATE TABLE IF NOT EXISTS doctor_rooms (doctor_id INTEGER PRIMARY KEY, "
              "room_no TEXT, floor INTEGER, directions TEXT, updated_at TEXT)")
    have = {r[0] for r in c.execute("SELECT doctor_id FROM doctor_rooms")}
    for d in DOCTORS:
        if d["id"] not in have:
            f, r, t = _default_room(d)
            c.execute("INSERT INTO doctor_rooms VALUES (?,?,?,?,datetime('now'))", (d["id"], r, f, t))


def _room_text(c, doctor_name):
    d = next((d for d in DOCTORS if d["name"] == doctor_name), None)
    if not d:
        return ""
    r = c.execute("SELECT directions FROM doctor_rooms WHERE doctor_id=?", (d["id"],)).fetchone()
    return r[0] if r else ""


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, phone TEXT, service TEXT, doctor TEXT DEFAULT '',
            start TEXT, end TEXT, status TEXT DEFAULT 'booked');
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caller TEXT, phone TEXT, message TEXT, urgent INTEGER, created_at TEXT);
        CREATE TABLE IF NOT EXISTS visitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor TEXT, visiting TEXT, arrived_at TEXT);
        CREATE TABLE IF NOT EXISTS escalations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reason TEXT, caller TEXT, phone TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, email TEXT, phone TEXT, address TEXT, reason TEXT,
            first_visit INTEGER, doctor TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS waitlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER, doctor TEXT, status TEXT DEFAULT 'waiting', created_at TEXT);
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER, email TEXT, message TEXT, created_at TEXT);
        """)
        # Upgrade older tables without deleting the database
        a_cols = [r[1] for r in c.execute("PRAGMA table_info(appointments)")]
        for col, ddl in [("doctor", "TEXT DEFAULT ''"),
                         ("patient_id", "INTEGER"),
                         ("reminder_sent_at", "TEXT"),
                         ("attendance", "TEXT DEFAULT ''"),
                         ("response_text", "TEXT DEFAULT ''"),
                         ("response_at", "TEXT")]:
            if col not in a_cols:
                c.execute(f"ALTER TABLE appointments ADD COLUMN {col} {ddl}")

        p_cols = [r[1] for r in c.execute("PRAGMA table_info(patients)")]
        for col, ddl in [("country", "TEXT DEFAULT ''"),
                         ("phone_type", "TEXT DEFAULT ''"),
                         ("last_attendance", "TEXT DEFAULT ''"),
                         ("last_attendance_at", "TEXT")]:
            if col not in p_cols:
                c.execute(f"ALTER TABLE patients ADD COLUMN {col} {ddl}")

        _seed_rooms(c)

init_db()


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M")


def _is_free(conn, start, end, doctor=""):
    clash = conn.execute(
        "SELECT 1 FROM appointments WHERE status='booked' AND doctor = ? "
        "AND start < ? AND end > ?",
        (doctor, _fmt(end), _fmt(start)),
    ).fetchone()
    return clash is None


def _day_slots(conn, d, doctor_name, mins):
    """Open start times (HH:MM) for one doctor on one date."""
    slots = []
    if d.weekday() in CLOSED_WEEKDAYS:
        return slots
    cur = datetime.combine(d, OPEN_TIME)
    last_end = datetime.combine(d, CLOSE_TIME)
    while cur + timedelta(minutes=mins) <= last_end:
        end = cur + timedelta(minutes=mins)
        if cur > datetime.now() and _is_free(conn, cur, end, doctor_name):
            slots.append(cur.strftime("%H:%M"))
        cur += timedelta(minutes=SLOT_MINUTES)
    return slots


def _notify_waitlist(conn, doctor, start):
    """Queue a notification for everyone waiting on this doctor. Returns how many."""
    if not doctor:
        return 0
    waiting = conn.execute(
        "SELECT w.id AS wid, p.id AS pid, p.name AS pname, p.email AS pemail "
        "FROM waitlist w JOIN patients p ON p.id = w.patient_id "
        "WHERE w.doctor = ? AND w.status = 'waiting'",
        (doctor,),
    ).fetchall()
    for w in waiting:
        msg = (f"Hi {w['pname']}, a slot has opened with {doctor} on {start}. "
               f"Reply or call us to book it.")
        conn.execute(
            "INSERT INTO notifications (patient_id, email, message, created_at) VALUES (?,?,?,?)",
            (w["pid"], w["pemail"], msg, _now()),
        )
        conn.execute("UPDATE waitlist SET status='notified' WHERE id=?", (w["wid"],))
    return len(waiting)


@mcp.tool()
def get_business_info(topic: str = "general") -> str:
    """Answer questions about hours, address, phone, services, parking, insurance,
    payment or cancellation policy."""
    t = topic.strip().lower()
    if t in FAQS:
        return FAQS[t]
    if "hour" in t or "open" in t:
        return BUSINESS["hours"]
    if "address" in t or "location" in t or "where" in t:
        return BUSINESS["address"]
    if "phone" in t or "contact" in t:
        return BUSINESS["phone"]
    if "service" in t:
        return "We offer: " + ", ".join(f"{s} ({m} min)" for s, m in SERVICES.items())
    return (f"{BUSINESS['name']}. Hours: {BUSINESS['hours']} Address: {BUSINESS['address']}. "
            f"Services: {', '.join(SERVICES)}.")


@mcp.tool()
def list_specialties() -> list[dict]:
    """List the specialties we offer and how many doctors each has."""
    return [{"specialty": s, "doctors": len(SPECIALTY_DOCTORS[s])} for s in SPECIALTIES]

@mcp.tool()
def get_doctor_directions(doctor: str) -> str:
    """How a patient finds a doctor's room (floor, room number, signboard). Accepts a name or list number."""
    found = find_doctor(doctor)
    if len(found) != 1:
        return "Please tell me exactly which doctor (name or list number)."
    with db() as c:
        r = c.execute("SELECT room_no, floor, directions FROM doctor_rooms WHERE doctor_id=?",
                      (found[0]["id"],)).fetchone()
    return f"{found[0]['name']} - Room {r[0]}, floor {r[1]}. {r[2]}" if r else "No room is recorded yet."


@mcp.tool()
def set_doctor_room(doctor: str, room_no: str, floor: int, directions: str = "", staff_pin: str = "") -> str:
    """STAFF ONLY: change a doctor's room. Needs the staff PIN."""
    pin = os.getenv("STAFF_PIN", "")
    if not pin or staff_pin != pin:
        return "Wrong or missing staff PIN."
    found = find_doctor(doctor)
    if len(found) != 1:
        return "Doctor not found or not exact."
    d = found[0]
    ordinal = _ORD.get(int(floor), f"{int(floor)}th")
    text = directions.strip() or (
        f"Take the lift to the {ordinal} floor. You will see a signboard with {d['name']}'s name - "
        f"follow it to Room {room_no}. Have a happy visit!")
    with db() as c:
        c.execute("INSERT OR REPLACE INTO doctor_rooms VALUES (?,?,?,?,?)",
                  (d["id"], str(room_no), int(floor), text, _now()))
    return f"Saved: {d['name']} - Room {room_no}, floor {floor}."


@mcp.tool()
def list_doctors(specialty: str = "") -> list[dict]:
    """List doctors with their list numbers. Pass a specialty such as 'ortho', 'cardio',
    'gyneco', 'physio' or 'general'. Leave empty to list all doctors."""
    if not specialty.strip():
        return DOCTORS
    s = resolve_specialty(specialty)
    if s is None:
        return [{"error": f"Unknown specialty. We have: {', '.join(SPECIALTIES)}."}]
    return [d for d in DOCTORS if d["specialty"] == s]


@mcp.tool()
def get_doctor(doctor: str) -> dict:
    """Look up one doctor by list number (1-55), full name or partial name."""
    found = find_doctor(doctor)
    if not found:
        return {"error": "No doctor matches that. Ask the caller to pick a name or number from the list."}
    if len(found) > 1:
        return {"error": "More than one doctor matches. Ask which one.", "matches": found}
    return found[0]


@mcp.tool()
def save_patient_details(name: str, email: str, country: str, phone: str, address: str,
                         reason: str, first_visit: bool, doctor: str) -> dict:
    """Save the patient's intake answers. Required before showing slots or booking.
    country is the patient's country (e.g. India). The phone number is checked against
    that country's rules. Returns a patient_id to use in later calls."""
    fields = {"name": name, "email": email, "country": country, "phone": phone,
              "address": address, "reason": reason, "doctor": doctor}
    missing = [k for k, v in fields.items() if not str(v).strip()]
    if missing:
        return {"error": f"Still need: {', '.join(missing)}."}
    if "@" not in email or "." not in email.split("@")[-1]:
        return {"error": "That email doesn't look valid. Ask the caller to repeat it."}
    check = validate_phone(country, phone)
    if not check["ok"]:
        return {"error": check["error"]}
    found = find_doctor(doctor)
    if len(found) != 1:
        return {"error": "Doctor not recognised. Use get_doctor first."}
    with db() as c:
        cur = c.execute(
            "INSERT INTO patients (name, email, phone, address, reason, first_visit, doctor, "
            "created_at, country, phone_type) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (name.strip(), email.strip(), check["e164"], address.strip(), reason.strip(),
             int(first_visit), found[0]["name"], _now(), check["country"], check["type"]),
        )
        pid = cur.lastrowid
    return {"patient_id": pid, "doctor": found[0]["name"], "phone": check["e164"],
            "phone_type": check["type"], "message": "Details saved. You can now check availability."}

@mcp.tool()
def get_week_availability(patient_id: int, doctor: str, start_day: str = "") -> dict:
    """Open times for one doctor over 7 days. Needs the patient_id from save_patient_details.
    start_day is YYYY-MM-DD and defaults to today."""
    with db() as c:
        if c.execute("SELECT 1 FROM patients WHERE id=?", (patient_id,)).fetchone() is None:
            return {"error": "Patient details are required first. Collect them and call save_patient_details."}
        found = find_doctor(doctor)
        if len(found) != 1:
            return {"error": "Please choose a doctor by full name or list number."}
        doc = found[0]
        try:
            first = (datetime.strptime(start_day, "%Y-%m-%d").date()
                     if start_day.strip() else datetime.now().date())
        except ValueError:
            return {"error": "start_day must be YYYY-MM-DD."}
        mins = SERVICES["consultation"]
        days = []
        for i in range(7):
            d = first + timedelta(days=i)
            times = _day_slots(c, d, doc["name"], mins)
            if times:
                days.append({"day": d.isoformat(), "weekday": d.strftime("%A"), "times": times})
    return {"doctor": doc["name"], "specialty": doc["specialty"],
            "days": days, "no_slots_this_week": not days}


@mcp.tool()
def book_appointment(patient_id: int, doctor: str, day: str, at: str) -> str:
    """Book a consultation. day: YYYY-MM-DD, at: HH:MM (24-hour). Needs a patient_id."""
    with db() as c:
        p = c.execute("SELECT name, phone FROM patients WHERE id=?", (patient_id,)).fetchone()
        if p is None:
            return "Patient details are required first. Collect them and call save_patient_details."
        found = find_doctor(doctor)
        if len(found) != 1:
            return "Please choose a doctor by full name or list number."
        doc_name = found[0]["name"]
        try:
            start = datetime.strptime(f"{day} {at}", "%Y-%m-%d %H:%M")
        except ValueError:
            return "Please use date YYYY-MM-DD and time HH:MM (24-hour)."
        mins = SERVICES["consultation"]
        end = start + timedelta(minutes=mins)

        if start <= datetime.now():
            return "That time has already passed."
        if (start.weekday() in CLOSED_WEEKDAYS
                or start.time() < OPEN_TIME or end.time() > CLOSE_TIME):
            return f"That is outside opening hours. {BUSINESS['hours']}"
        if not _is_free(c, start, end, doc_name):
            return "That slot is taken. Use get_week_availability to find another time."

        cur = c.execute(
            "INSERT INTO appointments (patient_id, name, phone, service, doctor, start, end) "
            "VALUES (?,?,?,?,?,?,?)",
            (patient_id, p["name"], p["phone"], "consultation", doc_name, _fmt(start), _fmt(end)),
        )
        appt_id = cur.lastrowid
        room = _room_text(c, doc_name)
    return (f"Booked. Confirmation #{appt_id}: {doc_name} for {p['name']} on {day} at {at}. "
            f"{room}")


@mcp.tool()
def join_waitlist(patient_id: int, doctor: str) -> str:
    """Put a patient on the waiting list for a doctor who has no free slots this week."""
    with db() as c:
        p = c.execute("SELECT name, email, phone FROM patients WHERE id=?", (patient_id,)).fetchone()
        if p is None:
            return "Patient details are required first. Collect them and call save_patient_details."
        found = find_doctor(doctor)
        if len(found) != 1:
            return "Please choose a doctor by full name or list number."
        doc_name = found[0]["name"]
        exists = c.execute(
            "SELECT 1 FROM waitlist WHERE patient_id=? AND doctor=? AND status='waiting'",
            (patient_id, doc_name),
        ).fetchone()
        if not exists:
            c.execute(
                "INSERT INTO waitlist (patient_id, doctor, created_at) VALUES (?,?,?)",
                (patient_id, doc_name, _now()),
            )
    return (f"{p['name']} is on the waiting list for {doc_name}. We will contact "
            f"{p['email']} and {p['phone']} if a slot opens after a cancellation.")

def _phone_like(phone):
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    return "%" + digits[-9:]


@mcp.tool()
def find_appointments(phone: str) -> list[dict]:
    """Find upcoming appointments for a phone number."""
    with db() as c:
        rows = c.execute(
            "SELECT id, name, service, doctor, start FROM appointments "
            "WHERE phone LIKE ? AND status='booked' AND start >= ? ORDER BY start",
            (_phone_like(phone), _now()),
        ).fetchall()
    return [dict(r) for r in rows]


@mcp.tool()
def cancel_appointment(appointment_id: int, phone: str) -> str:
    """Cancel an appointment. The phone number must match the booking."""
    with db() as c:
        row = c.execute(
            "SELECT id, doctor, start FROM appointments "
            "WHERE id=? AND phone LIKE ? AND status='booked'",
            (appointment_id, _phone_like(phone)),
        ).fetchone()
        if row is None:
            return "I couldn't find a matching booking for that number."
        c.execute("UPDATE appointments SET status='cancelled' WHERE id=?", (appointment_id,))
        notified = _notify_waitlist(c, row["doctor"], row["start"])
    extra = f" {notified} waiting patient(s) will be told about the opening." if notified else ""
    return f"Appointment #{appointment_id} has been cancelled.{extra}"


@mcp.tool()
def take_message(caller_name: str, country: str, phone: str, message: str, urgent: bool = False) -> str:
    """Leave a message for the staff. country is the caller's country."""
    check = validate_phone(country, phone)
    if not check["ok"]:
        return check["error"]
    with db() as c:
        c.execute(
            "INSERT INTO messages (caller, phone, message, urgent, created_at) VALUES (?,?,?,?,?)",
            (caller_name, check["e164"], message, int(urgent), _now()),
        )
    return "Message saved. Our team will call back" + (" as soon as possible." if urgent else " today.")


@mcp.tool()
def check_in_visitor(visitor_name: str, visiting: str) -> str:
    """Sign in a visitor or patient who has arrived and tell staff."""
    with db() as c:
        c.execute(
            "INSERT INTO visitors (visitor, visiting, arrived_at) VALUES (?,?,?)",
            (visitor_name, visiting, _now()),
        )
    return f"Welcome, {visitor_name}. I've let {visiting} know you're here. Please take a seat."


@mcp.tool()
def transfer_to_human(reason: str, caller_name: str = "", phone: str = "") -> str:
    """Hand off to a human for emergencies, complaints, billing disputes or anything unclear."""
    with db() as c:
        c.execute(
            "INSERT INTO escalations (reason, caller, phone, created_at) VALUES (?,?,?,?)",
            (reason, caller_name, phone, _now()),
        )
    return f"I've alerted a staff member. You can also call us directly at {BUSINESS['phone']}."


@mcp.tool()
def daily_report(day: str = "") -> dict:
    """STAFF ONLY. End-of-day report: patients per doctor for one day (YYYY-MM-DD, default today).
    Also saves a CSV in the reports folder."""
    day = day.strip() or datetime.now().strftime("%Y-%m-%d")
    with db() as c:
        rows = c.execute(
            "SELECT doctor, COUNT(*) AS n FROM appointments "
            "WHERE status='booked' AND substr(start,1,10)=? GROUP BY doctor",
            (day,),
        ).fetchall()
    counts = {r["doctor"]: r["n"] for r in rows}
    report = [
        {"doctor_no": d["id"], "doctor": d["name"], "specialty": d["specialty"],
         "patients": counts.get(d["name"], 0)}
        for d in DOCTORS
    ]
    total = sum(r["patients"] for r in report)

    REPORTS_DIR.mkdir(exist_ok=True)
    csv_path = REPORTS_DIR / f"report_{day}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["doctor_no", "doctor", "specialty", "patients"])
        writer.writeheader()
        writer.writerows(report)

    return {"day": day, "total_patients": total,
            "doctors_with_patients": sum(1 for r in report if r["patients"]),
            "csv_file": str(csv_path), "report": report}


@mcp.tool()
def list_waitlist_notifications() -> dict:
    """STAFF ONLY. The latest waitlist notifications that were queued after cancellations."""
    with db() as c:
        rows = c.execute(
            "SELECT email, message, created_at FROM notifications ORDER BY id DESC LIMIT 20"
        ).fetchall()
    return {"notifications": [dict(r) for r in rows]}

def _check_pin(pin):
    if not STAFF_PIN:
        return "The staff PIN is not set. Add STAFF_PIN=... to the .env file and restart the server."
    if str(pin).strip() != STAFF_PIN:
        return "That staff PIN is not correct, so I can't show patient details."
    return None


def _report_rows(conn, doc_name, day):
    rows = conn.execute(
        "SELECT a.start AS start, COALESCE(p.name, a.name, '') AS name, "
        "COALESCE(p.country, '') AS country, COALESCE(p.phone, a.phone, '') AS phone, "
        "COALESCE(p.email, '') AS email "
        "FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id "
        "WHERE a.status='booked' AND a.doctor=? AND substr(a.start,1,10)=? "
        "ORDER BY a.start", (doc_name, day)).fetchall()
    return [dict(zip(REPORT_COLUMNS,
                     [r["start"][11:16], r["name"], r["country"], r["phone"], r["email"]]))
            for r in rows]


def _unique_path(folder, stem, ext):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stem}.{ext}"
    n = 2
    while path.exists():
        path = folder / f"{stem} ({n}).{ext}"
        n += 1
    return path


def _write_export(rows, path, fmt):
    if fmt == "csv":
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=REPORT_COLUMNS)
            w.writeheader()
            w.writerows(rows)
    else:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Report"
        ws.append(REPORT_COLUMNS)
        for r in rows:
            ws.append([r[c] for c in REPORT_COLUMNS])
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = (
                max(len(str(c.value or "")) for c in col) + 3)
        wb.save(path)


@mcp.tool()
def doctor_report(doctor: str, staff_pin: str, day: str = "") -> dict:
    """STAFF ONLY. Report for one doctor on one day (YYYY-MM-DD, default today): how many
    patients and their name, country, phone and email. Needs the staff PIN."""
    problem = _check_pin(staff_pin)
    if problem:
        return {"error": problem}
    found = find_doctor(doctor)
    if len(found) != 1:
        return {"error": "Which doctor? Give the full name or list number."}
    doc = found[0]
    day = day.strip() or datetime.now().strftime("%Y-%m-%d")
    with db() as c:
        rows = _report_rows(c, doc["name"], day)
    return {"doctor": doc["name"], "specialty": doc["specialty"], "day": day,
            "patients_count": len(rows), "patients": rows}


@mcp.tool()
def export_doctor_report(doctor: str, file_format: str, staff_pin: str, day: str = "") -> dict:
    """STAFF ONLY. Save a doctor's report to the Downloads folder as csv or xlsx.
    Only call this after the staff member says they want the export."""
    problem = _check_pin(staff_pin)
    if problem:
        return {"error": problem}
    fmt = file_format.strip().lower().lstrip(".")
    if fmt not in ("csv", "xlsx"):
        return {"error": "Please choose csv or xlsx."}
    found = find_doctor(doctor)
    if len(found) != 1:
        return {"error": "Which doctor? Give the full name or list number."}
    doc = found[0]
    day = day.strip() or datetime.now().strftime("%Y-%m-%d")
    with db() as c:
        rows = _report_rows(c, doc["name"], day)
    stem = f"{doc['name'].replace('.', '').strip()} {day}"
    path = _unique_path(DOWNLOADS_DIR, stem, fmt)
    try:
        _write_export(rows, path, fmt)
    except PermissionError:
        return {"error": "I couldn't save the file. Close it if it's open in Excel and try again."}
    return {"saved_to": str(path), "patients_count": len(rows)}

if __name__ == "__main__":
    import uvicorn
    from auth import init_auth
    from guard import AuthGuard

    init_auth()
    uvicorn.run(AuthGuard(mcp.streamable_http_app()), host="127.0.0.1", port=8000, timeout_keep_alive=300)