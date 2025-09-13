# app/services/contracts_service.py
from __future__ import annotations
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_contracts_by_user(
    session: AsyncSession,
    *,
    user_id: int,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Return contracts for one user (most recent first).
    """
    sql = text("""
        SELECT
          id,
          user_id,
          tenant,
          doc_type,
          original_filename,
          file_url,
          sha256,
          uploaded_at,
          created_at
        FROM contracts
        WHERE user_id = :uid
        ORDER BY COALESCE(uploaded_at, created_at) DESC, id DESC
        LIMIT :lim OFFSET :off
    """)
    rows = (
        await session.execute(
            sql, {"uid": int(user_id), "lim": int(limit), "off": int(offset)}
        )
    ).mappings().all()

    return [
        {
            "id": r["id"],
            "user_id": r["user_id"],
            "tenant": r["tenant"],
            "doc_type": r["doc_type"],
            "original_filename": r["original_filename"],
            "file_url": r["file_url"],
            "sha256": r["sha256"],
            "uploaded_at": r["uploaded_at"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
