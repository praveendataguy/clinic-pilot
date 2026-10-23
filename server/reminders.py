"""Appointment reminders: emails each patient 1 hour before their appointment and
reads their reply (YES = attending, CANCEL = cancel).

Run from the project folder, in a terminal that shows (.venv):
    python server/reminders.py                       keep running, checks every minute
    python server/reminders.py --once                one check, then stop
    python server/reminders.py --send-now 12         send the reminder for appointment 12 now
    python server/reminders.py --reply 12 "cancel"   pretend the patient of appointment 12 replied
"""
import email
import imaplib
import os
import re
import smtplib
import sys
import time
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr

from dotenv import load_dotenv

load_dotenv()

from main import BUSINESS, _notify_waitlist, _now, db, init_db, _room_text  # noqa: E402

init_db()  # makes sure the new columns exist

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")
MAIL_USER = os.getenv("MAIL_USER", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_FROM = os.getenv("MAIL_FROM", "") or MAIL_USER
REMINDER_MINUTES = int(os.getenv("REMINDER_MINUTES", "60"))
CHECK_SECONDS = 60

TAG = re.compile(r"\[#(\d+)\]")


# ---------------------------------------------------------------- email text
def build_email(appt):
    start = datetime.strptime(appt["start"], "%Y-%m-%d %H:%M")
    when = start.strftime("%A, %d %B %Y at %H:%M")
    msg = EmailMessage()
    msg["Subject"] = f"Appointment reminder [#{appt['id']}] - {appt['doctor']} at {start:%H:%M}"
    msg["From"] = MAIL_FROM or "reception@localhost"
    msg["To"] = appt["email"]
    msg.set_content(
        f"Hello {appt['name']},\n\n"
        f"This is a reminder from {BUSINESS['name']}: your appointment with {appt['doctor']} "
        f"is in 1 hour, on {when}.\n\n"
        f"Could you please confirm that you are attending? Just reply to this email with one word:\n"
        f"    YES      if you will attend\n"
        f"    CANCEL   if you would like to cancel\n\n"
        f"{appt.get('directions', '')}\n\n"
        f"Address: {BUSINESS['address']}   Phone: {BUSINESS['phone']}\n\n"
        f"Thank you,\n{BUSINESS['name']}\n"
    )
    return msg


def send_email(msg):
    """Send through SMTP. Without MAIL_USER/MAIL_PASSWORD it only prints (dry run)."""
    if not (MAIL_USER and MAIL_PASSWORD):
        print(f"[dry run - no mail account set] To: {msg['To']}\nSubject: {msg['Subject']}\n"
              f"{msg.get_content()}\n")
        return "dry-run"
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.starttls()
        s.login(MAIL_USER, MAIL_PASSWORD)
        s.send_message(msg)
    return "sent"


# ------------------------------------------------------------- reading replies
def parse_reply(text):
    """Return ('confirmed' | 'cancelled' | 'unclear', short cleaned text)."""
    kept = []
    for line in str(text).splitlines():
        s = line.strip()
        if re.match(r"^(on .+wrote:?|-+\s*original message\s*-+|from:|sent:|to:|subject:)", s, re.I):
            break
        if s.startswith(">"):
            continue
        kept.append(s)
    cleaned = " ".join(x for x in kept if x)[:300]
    low = cleaned.lower()
    low = re.sub(r"(do not|don't|dont|not)\s+(want to\s+)?cancel", " ", low)
    if re.search(r"\bcancel|not attending|not coming|can't make|cannot make|can not attend|won't be able", low):
        return "cancelled", cleaned
    if re.search(r"\b(yes|yep|yeah|confirm|confirmed|attending|attend|coming|will be there|ok|okay|sure)\b", low):
        return "confirmed", cleaned
    return "unclear", cleaned


def process_reply(appt_id, text, from_addr=None):
    """Store a patient's answer. Returns a short message about what happened."""
    state, cleaned = parse_reply(text)
    with db() as c:
        a = c.execute(
            "SELECT a.id, a.status, a.doctor, a.start, a.patient_id, p.email AS email "
            "FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id WHERE a.id=?",
            (appt_id,)).fetchone()
        if a is None:
            return f"appointment #{appt_id} not found"
        if from_addr and (a["email"] or "").strip().lower() != from_addr.strip().lower():
            return f"ignored: {from_addr} is not the patient's email for #{appt_id}"
        now = _now()
        c.execute("UPDATE appointments SET attendance=?, response_text=?, response_at=? WHERE id=?",
                  (state, cleaned, now, appt_id))
        if a["patient_id"]:
            c.execute("UPDATE patients SET last_attendance=?, last_attendance_at=? WHERE id=?",
                      (state, now, a["patient_id"]))
        extra = ""
        if state == "cancelled" and a["status"] == "booked":
            c.execute("UPDATE appointments SET status='cancelled' WHERE id=?", (appt_id,))
            n = _notify_waitlist(c, a["doctor"], a["start"])
            extra = f"; appointment cancelled, {n} waiting patient(s) notified"
    return f"#{appt_id}: {state}{extra}"


def _body_text(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        return ""
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")


def check_replies():
    """Read unread replies from the mailbox and store them."""
    if not (MAIL_USER and MAIL_PASSWORD):
        return
    try:
        box = imaplib.IMAP4_SSL(IMAP_HOST)
        box.login(MAIL_USER, MAIL_PASSWORD)
        box.select("INBOX")
        _, data = box.search(None, "UNSEEN", "SUBJECT", '"[#"')
        for num in data[0].split():
            _, parts = box.fetch(num, "(BODY.PEEK[])")
            msg = email.message_from_bytes(parts[0][1])
            subject = str(make_header(decode_header(msg.get("Subject", ""))))
            m = TAG.search(subject)
            if not m:
                continue
            result = process_reply(int(m.group(1)), _body_text(msg), parseaddr(msg.get("From", ""))[1])
            print("reply:", result)
            box.store(num, "+FLAGS", "\\Seen")
        box.logout()
    except Exception as e:  # network hiccups must not stop the worker
        print("could not check replies:", e)


# ------------------------------------------------------------- sending reminders
def _due(now):
    return (now.strftime("%Y-%m-%d %H:%M"),
            (now + timedelta(minutes=REMINDER_MINUTES)).strftime("%Y-%m-%d %H:%M"))


def send_reminder(appt_id, force=False):
    with db() as c:
        a = c.execute(
            "SELECT a.id, a.doctor, a.start, a.name, p.email AS email, a.reminder_sent_at AS sent "
            "FROM appointments a JOIN patients p ON p.id = a.patient_id "
            "WHERE a.id=? AND a.status='booked'", (appt_id,)).fetchone()
        if a is None or not a["email"]:
            return f"#{appt_id}: no booked appointment with an email"
        if a["sent"] and not force:
            return f"#{appt_id}: reminder already sent"
        appt = dict(a)
        appt["directions"] = _room_text(c, a["doctor"])
        how = send_email(build_email(appt))
        c.execute("UPDATE appointments SET reminder_sent_at=? WHERE id=?", (_now(), appt_id))
    return f"#{appt_id}: reminder {how} to {a['email']}"

def send_due():
    lo, hi = _due(datetime.now())
    with db() as c:
        ids = [r["id"] for r in c.execute(
            "SELECT a.id FROM appointments a JOIN patients p ON p.id = a.patient_id "
            "WHERE a.status='booked' AND a.reminder_sent_at IS NULL AND p.email != '' "
            "AND a.start > ? AND a.start <= ?", (lo, hi))]
    for i in ids:
        try:
            print(send_reminder(i))
        except Exception as e:
            print(f"#{i}: could not send ({e}); will retry")


def main():
    args = sys.argv[1:]
    if args[:1] == ["--send-now"]:
        print(send_reminder(int(args[1]), force=True))
    elif args[:1] == ["--reply"]:
        print(process_reply(int(args[1]), args[2] if len(args) > 2 else ""))
    elif args[:1] == ["--once"]:
        send_due()
        check_replies()
    else:
        mode = "sending real emails" if (MAIL_USER and MAIL_PASSWORD) else "DRY RUN (no MAIL_USER/MAIL_PASSWORD set)"
        print(f"Reminder worker started: {mode}. Press Ctrl+C to stop.")
        while True:
            send_due()
            check_replies()
            time.sleep(CHECK_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("stopped")