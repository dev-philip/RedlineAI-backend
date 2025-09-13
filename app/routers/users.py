# app/routers/users.py

# List contracts: GET /api/v1/users/123/contracts
# Get one: GET /api/v1/users/123/contracts/{contract_id}
# Pre-sign file: GET /api/v1/users/123/contracts/{contract_id}/presign?expires_in=600
# List documents w/ URLs: GET /api/v1/users/123/documents?include_urls=true&expires_in=600
# Overview: GET /api/v1/users/123/overview
from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_tidb_session
from app.services.contracts_service import list_contracts_by_user
from app.services.s3_service import S3Service
from app.dependencies import get_s3_service

router = APIRouter(prefix="/api/v1/users", tags=["users"])


# ---------- Pydantic models ----------
class ContractOut(BaseModel):
    id: str
    tenant: Optional[str] = None
    doc_type: Optional[str] = None
    original_filename: Optional[str] = None
    file_key: Optional[str] = None         # stored in contracts.s3_file_key (your key)
    sha256: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    presigned_url: Optional[str] = None    # filled only when requested


class UserOverviewOut(BaseModel):
    user_id: int
    total_contracts: int
    contracts_with_files: int
    last_uploaded_at: Optional[datetime]
    risks_total: int
    risks_high: int
    risks_medium: int
    risks_low: int
    open_alerts: int


class PresignOut(BaseModel):
    contract_id: str
    key: str
    url: str
    expires_in: int


# ---------- Helpers ----------
async def _contract_for_user_or_404(session: AsyncSession, user_id: int, contract_id: str) -> Dict[str, Any]:
    sql = text("""
        SELECT id, user_id, tenant, doc_type, original_filename, s3_file_key, sha256, uploaded_at
        FROM contracts
        WHERE id = :cid AND user_id = :uid
        LIMIT 1
    """)
    row = (await session.execute(sql, {"cid": contract_id, "uid": user_id})).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Contract not found for this user")
    return dict(row)


# ---------- Endpoints ----------

@router.get("/{user_id}/contracts", response_model=List[ContractOut])
async def list_user_contracts(
    user_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_tidb_session),
):
    """
    All contracts uploaded by a given user (paginated).
    """
    sql = text("""
        SELECT id, tenant, doc_type, original_filename, s3_file_key, sha256, uploaded_at
        FROM contracts
        WHERE user_id = :uid
        ORDER BY uploaded_at DESC, id DESC
        LIMIT :lim OFFSET :off
    """)
    rows = (await session.execute(sql, {"uid": user_id, "lim": limit, "off": offset})).mappings().all()

    return [
        ContractOut(
            id=r["id"],
            tenant=r["tenant"],
            doc_type=r["doc_type"],
            original_filename=r["original_filename"],
            file_key=r["s3_file_key"],
            sha256=r["sha256"],
            uploaded_at=r["uploaded_at"],
        )
        for r in rows
    ]


@router.get("/{user_id}/contracts/{contract_id}", response_model=ContractOut)
async def get_user_contract(
    user_id: int,
    contract_id: str,
    session: AsyncSession = Depends(get_tidb_session),
):
    """
    One contract (ensures it belongs to this user).
    """
    row = await _contract_for_user_or_404(session, user_id, contract_id)
    return ContractOut(
        id=row["id"],
        tenant=row["tenant"],
        doc_type=row["doc_type"],
        original_filename=row["original_filename"],
        file_key=row["s3_file_key"],
        sha256=row["sha256"],
        uploaded_at=row["uploaded_at"],
    )


@router.get("/{user_id}/contracts/{contract_id}/presign", response_model=PresignOut)
async def presign_contract_file(
    user_id: int,
    contract_id: str,
    expires_in: int = Query(3600, ge=60, le=60 * 60 * 24),
    session: AsyncSession = Depends(get_tidb_session),
    s3: S3Service = Depends(get_s3_service),
):
    """
    Return a time-limited, viewable link to the contract file in S3 (pre-signed URL).
    """
    row = await _contract_for_user_or_404(session, user_id, contract_id)
    key = row.get("s3_file_key")
    if not key:
        raise HTTPException(status_code=404, detail="No file attached to this contract")

    # Your S3Service should return a url string.
    url = await s3.generate_presigned_url(key=key, expires_in=expires_in)
    return PresignOut(contract_id=contract_id, key=key, url=url, expires_in=expires_in)


@router.get("/{user_id}/documents", response_model=List[ContractOut])
async def list_user_documents(
    user_id: int,
    include_urls: bool = Query(False, description="If true, include short-lived presigned URLs."),
    expires_in: int = Query(900, ge=60, le=60 * 60 * 24),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_tidb_session),
    s3: S3Service = Depends(get_s3_service),
):
    """
    Contracts with a stored file (optionally include pre-signed URLs).
    """
    sql = text("""
        SELECT id, tenant, doc_type, original_filename, s3_file_key, sha256, uploaded_at
        FROM contracts
        WHERE user_id = :uid AND s3_file_key IS NOT NULL AND s3_file_key <> ''
        ORDER BY uploaded_at DESC, id DESC
        LIMIT :lim OFFSET :off
    """)
    rows = (await session.execute(sql, {"uid": user_id, "lim": limit, "off": offset})).mappings().all()

    results: List[ContractOut] = []
    for r in rows:
        presigned: Optional[str] = None
        if include_urls and r["s3_file_key"]:
            presigned = await s3.generate_presigned_url(key=r["s3_file_key"], expires_in=expires_in)

        results.append(
            ContractOut(
                id=r["id"],
                tenant=r["tenant"],
                doc_type=r["doc_type"],
                original_filename=r["original_filename"],
                file_key=r["s3_file_key"],
                sha256=r["sha256"],
                uploaded_at=r["uploaded_at"],
                presigned_url=presigned,
            )
        )
    return results


@router.get("/{user_id}/overview", response_model=UserOverviewOut)
async def user_overview(
    user_id: int,
    session: AsyncSession = Depends(get_tidb_session),
):
    """
    Lightweight dashboard numbers for the user.
    """
    # totals
    total_contracts = (await session.execute(
        text("SELECT COUNT(*) FROM contracts WHERE user_id = :uid"),
        {"uid": user_id},
    )).scalar_one()

    contracts_with_files = (await session.execute(
        text("SELECT COUNT(*) FROM contracts WHERE user_id = :uid AND s3_file_key IS NOT NULL AND s3_file_key <> ''"),
        {"uid": user_id},
    )).scalar_one()

    last_uploaded_at = (await session.execute(
        text("SELECT MAX(uploaded_at) FROM contracts WHERE user_id = :uid"),
        {"uid": user_id},
    )).scalar_one()

    # risk counts by join
    risk_row = (await session.execute(
        text("""
            SELECT
              COUNT(*)                                                   AS total,
              SUM(CASE WHEN r.severity >= 8               THEN 1 ELSE 0 END) AS high,
              SUM(CASE WHEN r.severity BETWEEN 5 AND 7    THEN 1 ELSE 0 END) AS medium,
              SUM(CASE WHEN r.severity BETWEEN 1 AND 4    THEN 1 ELSE 0 END) AS low
            FROM risks r
            JOIN contracts c ON c.id = r.contract_id
            WHERE c.user_id = :uid
        """),
        {"uid": user_id},
    )).mappings().first() or {"total": 0, "high": 0, "medium": 0, "low": 0}

    # open alerts
    open_alerts = (await session.execute(
        text("""
            SELECT COUNT(*)
            FROM alerts a
            JOIN contracts c ON c.id = a.contract_id
            WHERE c.user_id = :uid AND a.status = 'open'
        """),
        {"uid": user_id},
    )).scalar_one()

    return UserOverviewOut(
        user_id=user_id,
        total_contracts=int(total_contracts or 0),
        contracts_with_files=int(contracts_with_files or 0),
        last_uploaded_at=last_uploaded_at,
        risks_total=int(risk_row.get("total", 0)),
        risks_high=int(risk_row.get("high", 0)),
        risks_medium=int(risk_row.get("medium", 0)),
        risks_low=int(risk_row.get("low", 0)),
        open_alerts=int(open_alerts or 0),
    )


@router.get(
    "/{user_id}/contracts",
    response_model=List[Dict[str, Any]],
    summary="List contracts uploaded by a user",
)
async def get_user_contracts(
    user_id: int = Path(..., description="User ID"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0, le=5000),
    session: AsyncSession = Depends(get_tidb_session),
):
    return await list_contracts_by_user(
        session,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )