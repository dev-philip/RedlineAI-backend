# app/services/notifiers.py
import os
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape

# ---------- ENV ----------
SENDGRID_API_KEY   = os.getenv("SENDGRID_API_KEY")
ALERTS_FROM_EMAIL  = os.getenv("ALERTS_FROM_EMAIL", "alerts@yourapp.com")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")  # e.g. "+15551112222"

# ---------- Optional SDKs ----------
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
except Exception:
    SendGridAPIClient = None
    Mail = None

try:
    from twilio.rest import Client as TwilioClient
except Exception:
    TwilioClient = None


# =========================================================
# Email utilities (validation + filter)
# =========================================================
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

def _valid_email(addr: str) -> bool:
    return bool(addr and _EMAIL_RE.match(addr.strip()))

def _filter_recipients(to: List[str]) -> List[str]:
    """Dedup, validate, and drop default 'legal@acme.com' if present."""
    cleaned = []
    seen = set()
    for a in to or []:
        a2 = (a or "").strip()
        if not a2 or a2.lower() == "legal@acme.com":
            continue
        if _valid_email(a2) and a2.lower() not in seen:
            seen.add(a2.lower())
            cleaned.append(a2)
    return cleaned[:50]  # guardrail


# =========================================================
# EMAIL (SendGrid)
# =========================================================
def send_email(to: List[str], subject: str, html: str) -> Dict[str, Any]:
    """
    Sends HTML email via SendGrid. Falls back to dev-mode print if not configured.
    Skips sending if 'to' is empty or only contains default placeholders.
    """
    print("=== EMAIL ===")
    print("Original To:", to)
    print("Subject:", subject)

    recipients = _filter_recipients(to or [])
    if not recipients:
        msg = "No valid recipients after filtering."
        print("SKIP EMAIL:", msg)
        return {"status": "skipped", "reason": msg}

    if not SENDGRID_API_KEY or not SendGridAPIClient or not Mail:
        # Dev-mode fallback
        print("SendGrid not configured; dev-print only.")
        print("To:", recipients)
        print("From:", ALERTS_FROM_EMAIL)
        print("Subject:", subject)
        print("HTML:\n", html)
        return {"status": "dev", "to": recipients}

    try:
        message = Mail(
            from_email=ALERTS_FROM_EMAIL,   # must be verified in SendGrid
            to_emails=recipients,
            subject=subject,
            html_content=html,
        )
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        resp = sg.send(message)
        return {"status": "success", "code": getattr(resp, "status_code", None)}
    except Exception as e:
        print("EMAIL ERROR:", e)
        return {"status": "error", "message": str(e)}


# =========================================================
# Phone helpers
# =========================================================
_E164 = re.compile(r"^\+[1-9]\d{1,14}$")

def _is_valid_e164(num: str) -> bool:
    return bool(num and _E164.match(num))


# =========================================================
# SMS (Twilio) - optional helper used by your dispatcher
# =========================================================
def send_sms(to_number: str, body: str) -> Dict[str, Any]:
    """
    Sends a text message. Dev-prints if Twilio not configured.
    """
    print("=== SMS ===")
    print("To:", to_number)
    print("Body:", body)

    # if not _is_valid_e164(to_number):
    #     msg = "Invalid or missing destination number (E.164 required)."
    #     print("SKIP SMS:", msg)
    #     return {"status": "error", "message": msg}

    # if not _is_valid_e164(TWILIO_FROM_NUMBER or ""):
    #     msg = "TWILIO_FROM_NUMBER not configured or invalid."
    #     print("SKIP SMS:", msg)
    #     return {"status": "error", "message": msg}

    # if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TwilioClient):
    #     print("Twilio not configured; dev-print only.")
    #     return {"status": "dev", "to": to_number, "body": body}

    # try:
    #     client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    #     msg = client.messages.create(
    #         to=to_number,
    #         from_=TWILIO_FROM_NUMBER,
    #         body=body[:1600],
    #     )
    #     return {"status": "success", "sid": getattr(msg, "sid", None)}
    # except Exception as e:
    #     print("SMS ERROR:", e)
    #     return {"status": "error", "message": str(e)}


# =========================================================
# CALL (Twilio with inline TwiML)
# =========================================================
def _build_twiml(body: str) -> str:
    text = (body or "This is an automated contract alert.").strip()
    text = text[:1600]  # safety guard
    # Escape to be safe in XML and keep voice pleasant
    safe = xml_escape(text, {"'": "&apos;", '"': "&quot;"})
    return f'<Response><Say voice="alice">{safe}</Say></Response>'

def make_call(to_number: str, body: str) -> Dict[str, Any]:
    """
    Places a voice call using inline TwiML <Say> with the alert text.
    Dev-prints if Twilio not configured.
    """
    print("=== CALL ===")
    print("To:", to_number)
    print("Body:", body)

    # Validate destination
    if not _is_valid_e164(to_number):
        msg = "Invalid or missing destination number (must be E.164 like +15551234567)."
        print("SKIP CALL:", msg)
        return {"status": "error", "message": msg}

    # Validate source
    if not _is_valid_e164(TWILIO_FROM_NUMBER or ""):
        msg = "TWILIO_FROM_NUMBER not configured or invalid (E.164 required)."
        print("SKIP CALL:", msg)
        return {"status": "error", "message": msg}

    twiml = _build_twiml(body)

    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TwilioClient):
        print("Twilio not configured; dev-print only.")
        print("Would call:", to_number)
        print("Twiml:", twiml)
        return {"status": "dev", "to": to_number, "twiml": twiml}

    try:
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        call = client.calls.create(
            to=to_number,
            from_=TWILIO_FROM_NUMBER,
            twiml=twiml,  # inline XML—no external URL needed
        )
        return {"status": "success", "call_sid": getattr(call, "sid", None)}
    except Exception as e:
        print("CALL ERROR:", e)
        return {"status": "error", "message": str(e)}


# =========================================================
# Calendar stub (kept for dispatcher compatibility)
# =========================================================
def add_google_calendar_event(summary: str, start: datetime, end: datetime,
                              attendees: Optional[List[str]] = None) -> bool:
    """
    TODO: implement google-api-python-client OAuth and insert an event.
    For now, dev-print and return False.
    """
    print("=== CALENDAR ===")
    print("Summary:", summary)
    print("Start:", start)
    print("End:", end)
    print("Attendees:", attendees or [])
    return False
