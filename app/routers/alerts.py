from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_tidb_session
from app.services.alert_dispatcher import fetch_due_alerts, run_alerts_once
from app.services.alerts_service import list_alerts_by_contract

router = APIRouter()

@router.get("/due")
async def list_due_alerts(
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_tidb_session),
):
    """See what would be sent if we dispatch now (debug/inspection)."""
    alerts = await fetch_due_alerts(session, limit=limit)
    return {"count": len(alerts), "alerts": alerts}

@router.post("/dispatch")
async def dispatch_alerts_now(
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_tidb_session),
):
    """
    Deliver any due alerts:
    - status='open'
    - due_at is NULL or in the past
    """
    # fetch_due_alerts already defaults to 50; run_alerts_once calls it internally.
    # If you want the limit respected, add a `limit` param to run_alerts_once and pass it through.
    sent = await run_alerts_once(session)
    return {"dispatched": sent}


@router.get(
    "/contracts/{contract_id}",
    response_model=List[Dict[str, Any]],
    summary="List alerts for a contract for a user",
)
async def get_contract_alerts(
    contract_id: str = Path(..., description="Contract ID (UUID)"),
    status: Optional[str] = Query(
        None, description="Filter by status: open, sent, failed"
    ),
    min_severity: int = Query(
        0, ge=0, le=10, description="Only alerts with severity >= this value"
    ),
    limit: int = Query(200, ge=1, le=1000),
    session: AsyncSession = Depends(get_tidb_session),
):
    return await list_alerts_by_contract(
        session,
        contract_id=contract_id,
        status=status,
        min_severity=min_severity,
        limit=limit,
    )