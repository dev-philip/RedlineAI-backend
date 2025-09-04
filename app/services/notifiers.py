# app/services/notifiers.py
import os
from typing import List, Optional
from datetime import datetime

SENDGRID_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL   = os.getenv("ALERTS_FROM_EMAIL", "alerts@yourapp.com")

def send_email(to: List[str], subject: str, html: str) -> None:
    print("=== EMAIL ===")
    print("To:", to)
    print("Subject:", subject)
    print("HTML:\n", html)
    # Real impl (commented)
    # if not SENDGRID_KEY:
    #     raise RuntimeError("SENDGRID_API_KEY not set")
    # from sendgrid import SendGridAPIClient
    # from sendgrid.helpers.mail import Mail
    # msg = Mail(from_email=FROM_EMAIL, to_emails=to, subject=subject, html_content=html)
    # SendGridAPIClient(SENDGRID_KEY).send(msg)

def make_call(to_number: str, body: str) -> None:
    print("=== Make Call ===")
    print("To:", to_number)
    print("Body:", body)
    # Real impl (commented)
    # from twilio.rest import Client
    # sid   = os.getenv("TWILIO_ACCOUNT_SID")
    # token = os.getenv("TWILIO_AUTH_TOKEN")
    # from_ = os.getenv("TWILIO_FROM_NUMBER")
    # if not (sid and token and from_):
    #     raise RuntimeError("Twilio env vars not set")
    # Client(sid, token).messages.create(to=to_number, from_=from_, body=body)

def send_sms(to_number: str, body: str) -> None:
    print("=== SMS ===")
    print("To:", to_number)
    print("Body:", body)
    # Real impl (commented)
    # from twilio.rest import Client
    # sid   = os.getenv("TWILIO_ACCOUNT_SID")
    # token = os.getenv("TWILIO_AUTH_TOKEN")
    # from_ = os.getenv("TWILIO_FROM_NUMBER")
    # if not (sid and token and from_):
    #     raise RuntimeError("Twilio env vars not set")
    # Client(sid, token).messages.create(to=to_number, from_=from_, body=body)

def add_google_calendar_event(summary: str, start: datetime, end: datetime,
                              attendees: Optional[List[str]] = None) -> bool:
    print("=== CALENDAR ===")
    print("Summary:", summary)
    print("Start:", start, "End:", end)
    print("Attendees:", attendees)
    # Real impl: google-api-python-client
    return False
