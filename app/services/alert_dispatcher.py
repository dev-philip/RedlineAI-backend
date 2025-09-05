# app/services/alert_dispatcher.py
from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

# Your concrete senders
from app.services.notifiers import send_email, send_sms, make_call, add_google_calendar_event

log = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("America/New_York")  # change if you prefer another tz


# ---------------------- DB helpers ----------------------

async def fetch_due_alerts(session: AsyncSession, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Alerts ready to notify:
      - status in ('open','pending')
      - due_at is NULL or <= UTC now
    """
    sql = text(
        """
        SELECT
          id,
          contract_id,
          kind,
          severity,
          message,
          due_at,
          COALESCE(channel_json, JSON_OBJECT()) AS channel_json
        FROM alerts
        WHERE LOWER(TRIM(COALESCE(status,''))) IN ('open','pending')
          AND (due_at IS NULL OR due_at <= UTC_TIMESTAMP())
        ORDER BY COALESCE(due_at, UTC_TIMESTAMP()) ASC, id ASC
        LIMIT :lim
        """
    )
    rows = (await session.execute(sql, {"lim": int(limit)})).mappings().all()

    out: List[Dict[str, Any]] = []
    for r in rows:
        ch = r["channel_json"]
        if isinstance(ch, str):
            try:
                ch = json.loads(ch)
            except Exception:
                ch = {}
        out.append(
            {
                "id": r["id"],
                "contract_id": r["contract_id"],
                "kind": r["kind"],
                "severity": int(r["severity"] or 0),
                "message": r["message"] or "",
                "due_at": r["due_at"],        # datetime | None
                "channels": ch or {},         # {"email":[...], "sms":[...], "call":[...], "calendar":true}
            }
        )
    return out


async def fetch_user_contacts_for_contract(session: AsyncSession, contract_id: str) -> Dict[str, List[str]]:
    """
    Returns {"emails":[...], "phones":[...]} for the user that owns the contract.
    contracts.user_id -> users.id  (users.email, users.phone_number)
    """
    sql = text(
        """
        SELECT u.email, u.phone_number
        FROM contracts c
        LEFT JOIN users u ON u.id = c.user_id
        WHERE c.id = :cid
        LIMIT 1
        """
    )
    row = (await session.execute(sql, {"cid": contract_id})).mappings().first()

    emails: List[str] = []
    phones: List[str] = []
    if row:
        # If your columns might contain comma-separated values, split safely
        e = (row.get("email") or "").strip()
        p = (row.get("phone_number") or "").strip()
        if e:
            emails = [x.strip() for x in e.split(",") if x.strip()]
        if p:
            phones = [x.strip() for x in p.split(",") if x.strip()]

    return {"emails": emails, "phones": phones}


# ---------------------- channel logic ----------------------

def decide_channels(alert: Dict[str, Any]) -> Dict[str, Any]:
    """
    If channel_json is already set on the alert row, use it.
    Otherwise pick sensible defaults by severity.
    """
    ch = alert.get("channels") or {}
    if ch:
        return ch

    if alert.get("severity", 0) >= 8:
        # high severity: email + sms + optional calendar
        return {"email": [], "sms": [], "call": [], "calendar": True}
    return {"email": []}  # low/medium defaults to email only


def _merge_channels_with_user(channels: Dict[str, Any],
                              contacts: Dict[str, List[str]],
                              *,
                              fallback_email: str = "legal@acme.com") -> Dict[str, Any]:
    """
    Union channel recipients with user contacts.
    - 'email' gets user's email if present, else fallback
    - 'sms' and 'call' get user's phone if present
    Preserves existing values and de-duplicates.
    """
    def _dedup(seq: List[str]) -> List[str]:
        # order-preserving dedupe
        seen = set()
        out = []
        for s in seq:
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out

    merged = dict(channels)  # shallow copy

    # EMAIL
    if "email" not in merged:
        merged["email"] = []
    merged["email"] = _dedup(list(merged["email"]) + (contacts.get("emails") or []))
    if not merged["email"]:
        merged["email"] = [fallback_email]  # always have someone to email

    # SMS
    if "sms" not in merged:
        merged["sms"] = []
    merged["sms"] = _dedup(list(merged["sms"]) + (contacts.get("phones") or []))

    # CALL
    if "call" not in merged:
        merged["call"] = []
    merged["call"] = _dedup(list(merged["call"]) + (contacts.get("phones") or []))

    # CALENDAR: leave as-is; if not present, we won't force-enable it
    return merged


async def _send_via_channels(alert: Dict[str, Any], channels: Dict[str, Any]) -> None:
    """
    Dispatch the alert to each requested channel.
    Uses run_in_threadpool because notifiers are sync in this project.
    """
    subj = f"[Contract Alert] {alert['kind']} (sev {alert['severity']})"
    body_text = alert["message"] or "(no message)"
    contract_id = alert["contract_id"]

    # EMAIL
    if "email" in channels and channels["email"]:
        html = f"<p>{body_text}</p><p>Contract ID: {contract_id}</p>"
        await run_in_threadpool(send_email, channels["email"], subj, html)

    # SMS
    if "sms" in channels and channels["sms"]:
        for num in channels["sms"]:
            await run_in_threadpool(send_sms, num, f"{subj}: {body_text}")

    # VOICE CALL
    if "call" in channels and channels["call"]:
        for num in channels["call"]:
            await run_in_threadpool(make_call, num, f"{subj}: {body_text}")

    # CALENDAR (optional)
    if channels.get("calendar"):
        start: datetime = alert["due_at"] or datetime.utcnow()
        end: datetime = start
        try:
            await run_in_threadpool(
                add_google_calendar_event,
                f"{subj}",
                start,
                end,
                channels.get("email"),
            )
        except Exception as cal_err:
            log.warning("Calendar add failed for alert %s: %s", alert["id"], cal_err)


# ---------------------- top-level dispatcher ----------------------

async def run_alerts_once(
    session: AsyncSession,
    run_started_at_utc: Optional[datetime] = None,
    next_run_at_utc: Optional[datetime] = None,
) -> int:
    """
    1) fetch due alerts
    2) decide channels (severity/defaults or channel_json)
    3) enrich with contract owner contacts
    4) deliver
    5) mark sent/failed
    """

    
    # Fallback to now (UTC) if not provided
    run_started_at_utc = run_started_at_utc or datetime.now(tz=ZoneInfo("UTC"))

    # Safely convert to local time for readable logs
    ran_local = run_started_at_utc.astimezone(LOCAL_TZ)
    next_local = (
        next_run_at_utc.astimezone(LOCAL_TZ) if next_run_at_utc else None
    )

    print(
        "Run Schedular Olamide => [alerts] ran_at_local="
        f"{ran_local.isoformat()}  ran_at_utc={run_started_at_utc.isoformat()}  "
        f"next_run_local={(next_local.isoformat() if next_local else 'n/a')}"
    )

    alerts = await fetch_due_alerts(session)
    sent = 0

    for a in alerts:
        try:
            base_channels = decide_channels(a)
            contacts = await fetch_user_contacts_for_contract(session, a["contract_id"])
            channels = _merge_channels_with_user(base_channels, contacts)

            await _send_via_channels(a, channels)
            await _mark_alert(session, a["id"], "sent")
            sent += 1
        except Exception as e:
            log.exception("Alert %s delivery failed: %s", a.get("id"), e)
            await _mark_alert(session, a["id"], "failed", err=str(e))

    return sent


async def _mark_alert(session: AsyncSession, alert_id: int, status: str, err: Optional[str] = None) -> None:
    sql = text(
        """
        UPDATE alerts
        SET status = :st,
            notified_at = UTC_TIMESTAMP(),
            last_error = :err
        WHERE id = :aid
        """
    )
    await session.execute(sql, {"st": status, "err": err, "aid": alert_id})
    await session.commit()
