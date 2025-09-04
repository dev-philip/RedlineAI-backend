# app/routers/contracts_analysis_llm.py (snippet)
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_tidb_session
from app.services.contract_processing import process_contract  # heuristic version
from app.services.llm_contract_analysis import process_contract_with_llm
from app.config import settings


router = APIRouter()

@router.post("/contracts/{contract_id}/process", response_model=dict)
async def process_contract_endpoint(
    contract_id: str,
    session: AsyncSession = Depends(get_tidb_session),
    use_llm: bool = Query(True, description="Use the LLM pipeline (default True)"),
    model: Optional[str] = Query(None, description="Override model name, e.g., gpt-4o-mini"),
    batch_size: int = Query(10, ge=1, le=32),
):
    if use_llm:
        counts = await process_contract_with_llm(
            session,
            contract_id,
            model=model,
            batch_size=batch_size,
            policy_text=getattr(settings, "policy_text", None),
        )
    else:
        counts = await process_contract(session, contract_id)

    return {"contract_id": contract_id, **counts}


# @router.post("/contracts/{contract_id}/process", response_model=dict)
# async def process_contract_endpoint(
#     contract_id: str,
#     session: AsyncSession = Depends(get_tidb_session),
#     use_llm: bool = Query(True, description="Use the LLM pipeline (default True)"),
#     model: Optional[str] = Query(None, description="Override model name, e.g., gpt-4o-mini"),
#     batch_size: int = Query(10, ge=1, le=32),
# ):
#     if use_llm:
#         counts = await process_contract_with_llm(
#             session,
#             contract_id,
#             model=model,
#             batch_size=batch_size,
#             policy_text=getattr(settings, "policy_text", None),
#         )
#     else:
#         counts = await process_contract(session, contract_id)

#     return {"contract_id": contract_id, **counts}
