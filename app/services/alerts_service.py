# app/services/alerts_service.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_alerts_by_contract(
    session: AsyncSession,
    *,
    contract_id: str,
    status: Optional[str] = None,     # e.g. "open", "sent", "failed"
    min_severity: int = 0,            # 0–10
    limit: int = 200,                  # safety cap
) -> List[Dict[str, Any]]:
    """
    Return alerts for a contract. Optionally filter by status and min_severity.
    """
    base_sql = """
        SELECT
          id,
          contract_id,
          risk_id,
          kind,
          severity,
          message,
          due_at,
          status,
          notified_at,
          last_error,
          COALESCE(channel_json, JSON_OBJECT()) AS channel_json
        FROM alerts
        WHERE contract_id = :cid
          AND severity >= :minsev
    """
    params: Dict[str, Any] = {"cid": contract_id, "minsev": int(min_severity)}

    if status:
        # normalize to avoid case/whitespace surprises
        base_sql += " AND LOWER(TRIM(COALESCE(status,''))) = LOWER(TRIM(:status))"
        params["status"] = status

    base_sql += """
        ORDER BY severity DESC, COALESCE(due_at, NOW()) ASC, id DESC
        LIMIT :lim
    """
    params["lim"] = int(limit)

    rows = (await session.execute(text(base_sql), params)).mappings().all()

    out: List[Dict[str, Any]] = []
    for r in rows:
        ch = r["channel_json"]
        if isinstance(ch, (bytes, bytearray)):
            ch = ch.decode("utf-8", "ignore")
        if isinstance(ch, str):
            try:
                ch = json.loads(ch)
            except Exception:
                ch = {}
        out.append(
            {
                "id": r["id"],
                "contract_id": r["contract_id"],
                "risk_id": r["risk_id"],
                "kind": r["kind"],
                "severity": int(r["severity"] or 0),
                "message": r["message"],
                "due_at": r["due_at"],
                "status": r["status"],
                "notified_at": r["notified_at"],
                "last_error": r["last_error"],
                "channels": ch or {},
            }
        )
    return out