"""Sends one plain-text email. Never raises: it returns a short status instead.

Needs MAIL_USER and MAIL_PASSWORD in .env (a Gmail app password). Without them it prints the
email to the terminal ("dry-run") so the rest of the app still works.
"""
import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv

load_dotenv()


def send_email(to, subject, body):
    user = os.getenv("MAIL_USER", "")
    password = os.getenv("MAIL_PASSWORD", "")
    sender = os.getenv("MAIL_FROM", "") or user or "reception@localhost"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)
    if not (user and password):
        print(f"[dry run - no mail account set] To: {to}\nSubject: {subject}\n{body}\n")
        return "dry-run"
    try:
        with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"),
                          int(os.getenv("SMTP_PORT", "587")), timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
        return "sent"
    except Exception as e:
        print(f"could not send email to {to}: {e}")
        return f"failed: {e}"