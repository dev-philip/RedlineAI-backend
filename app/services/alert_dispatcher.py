from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

# Your concrete senders; keep these names/signatures the same.
# If your implementations are async already, call them directly instead of run_in_threadpool.
from app.services.notifiers import send_email, send_sms, add_google_calendar_event

log = logging.getLogger(__name__)


async def fetch_due_alerts(session: AsyncSession, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Pull alerts that are ready to notify:
      - status in ('open','pending')  <-- more forgiving than just 'open'
      - due_at is NULL or <= UTC now  <-- avoid local-time surprises
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
        WHERE status IN ('open','pending')
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
                "due_at": r["due_at"],    # datetime | None
                "channels": ch or {},     # {"email":[...], "sms":[...], "calendar":true}
            }
        )
    return out

async def mark_alert(session: AsyncSession, alert_id: int, status: str, err: Optional[str] = None) -> None:
    """
    Update status and bookkeeping after we attempt delivery.
    Allowed statuses in your schema: open | sent | failed
    """
    sql = text(
        """
        UPDATE alerts
        SET status = :st,
            notified_at = NOW(),
            last_error = :err
        WHERE id = :aid
        """
    )
    await session.execute(sql, {"st": status, "err": err, "aid": alert_id})
    await session.commit()


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
        return {
            "email": ["legal@acme.com"],
            "sms": ["+15550001111"],
            "calendar": True,
        }
    # low/medium: email only
    return {"email": ["legal@acme.com"]}


async def _send_via_channels(alert: Dict[str, Any], channels: Dict[str, Any]) -> None:
    """
    Dispatch the alert to each requested channel.
    Uses run_in_threadpool in case your notifiers are synchronous.
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

    # CALENDAR
    if channels.get("calendar"):
        # Use due_at if present; otherwise create an event for "now"
        start: datetime = alert["due_at"] or datetime.utcnow()
        end: datetime = start  # all-day or instant; adjust as you like
        # We don't fail the whole alert if calendar creation fails; just log.
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


async def run_alerts_once(session: AsyncSession) -> int:
    """
    Top-level dispatcher:
      1) fetch due alerts
      2) choose channels
      3) deliver
      4) mark sent/failed
    Returns number of alerts successfully sent.
    """
    alerts = await fetch_due_alerts(session)
    sent = 0

    for a in alerts:
        channels = decide_channels(a)
        try:
            await _send_via_channels(a, channels)
            await mark_alert(session, a["id"], "sent")
            sent += 1
        except Exception as e:
            log.exception("Alert %s delivery failed: %s", a["id"], e)
            await mark_alert(session, a["id"], "failed", err=str(e))

    return sent
