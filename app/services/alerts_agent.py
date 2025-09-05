# app/services/alert_agent.py
from __future__ import annotations
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import re
import json

from starlette.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from openai import OpenAI  # optional polish
except Exception:
    OpenAI = None

ALERT_SEVERITY_THRESHOLD_DEFAULT = 8
#Olamide Severity


# -------- decision + heuristics --------
def should_alert(risk: Dict[str, Any], *, threshold: int = ALERT_SEVERITY_THRESHOLD_DEFAULT) -> bool:
    return int(risk.get("severity", 0)) >= int(threshold)

def derive_due_at(risk: Dict[str, Any]) -> Optional[datetime]:
    text_ = f"{risk.get('rationale','')} {risk.get('suggested_fix','')}"
    m = re.search(r"(\d+)\s*day", text_, flags=re.I)
    if m:
        return datetime.utcnow() + timedelta(days=int(m.group(1)))
    return None

async def draft_alert_message(risk: Dict[str, Any], use_llm: bool = False) -> str:
    base = (
        f"High risk ({risk.get('severity')}/10) in {risk.get('clause_type','Clause')}.\n"
        f"Reason: {risk.get('rationale') or 'Review required.'}\n"
        f"Suggested fix: {risk.get('suggested_fix') or '—'}"
    )
    if not use_llm or OpenAI is None:
        return base

    def _call_llm() -> str:
        client = OpenAI()
        prompt = (
            "Rewrite the following risk note into one short, concise alert for a legal reviewer. "
            "Keep it under 2 sentences, imperatives allowed:\n\n" + base
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return resp.choices[0].message.content.strip()

    return await run_in_threadpool(_call_llm)


# -------- DB write helper (put it here so you don’t need a separate file) --------
async def create_alert_for_risk(
    session: AsyncSession,
    *,
    contract_id: str,
    risk_id: int,
    severity: int,
    message: str,
    due_at: Optional[datetime] = None,
    kind: str = "risk_high",
    status: str = "open",
    channels: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Insert (or upsert) an alert. If you added UNIQUE(contract_id, risk_id, kind),
    this will dedupe retries.
    """
    await session.execute(
        text("""
            INSERT INTO alerts
              (contract_id, risk_id, kind, severity, message, due_at, status, channel_json)
            VALUES
              (:cid, :rid, :kind, :sev, :msg, :due_at, :status, :ch)
            ON DUPLICATE KEY UPDATE
              severity = VALUES(severity),
              message  = VALUES(message),
              due_at   = VALUES(due_at),
              status   = VALUES(status),
              channel_json = VALUES(channel_json)
        """),
        {
            "cid": contract_id,
            "rid": risk_id,
            "kind": kind,
            "sev": int(severity),
            "msg": message,
            "due_at": due_at,                           # NULL ok
            "status": status,                           # "open" | "sent" | "failed"
            "ch": json.dumps(channels or {}),           # optional routing
        },
    )
