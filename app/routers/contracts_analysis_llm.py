# app/routers/contracts_analysis_llm.py
from typing import Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_tidb_session
from app.services.contract_processing import process_contract  # heuristic version
from app.services.llm_contract_analysis import process_contract_with_llm
from app.config import settings


router = APIRouter()

# ---- helpers ----
async def _get_existing_counts(session: AsyncSession, contract_id: str) -> Dict[str, int]:
    rows = (
        await session.execute(
            text("""
                SELECT
                  (SELECT COUNT(*) FROM clauses WHERE contract_id = :cid) AS clauses_cnt,
                  (SELECT COUNT(*) FROM risks   WHERE contract_id = :cid) AS risks_cnt
            """),
            {"cid": contract_id},
        )
    ).first()
    clauses_cnt = int(rows[0] if rows and rows[0] is not None else 0)
    risks_cnt   = int(rows[1] if rows and rows[1] is not None else 0)
    return {"clauses": clauses_cnt, "risks": risks_cnt}

async def _get_chunk_count(session: AsyncSession, contract_id: str) -> int:
    vec_tbl = getattr(settings, "langchain_table", "tidb_vector_langchain")
    q = text(
        f"""
        SELECT COUNT(*) FROM {vec_tbl}
        WHERE JSON_UNQUOTE(JSON_EXTRACT(meta, '$.contract_id')) = :cid
        """
    )
    return int((await session.execute(q, {"cid": contract_id})).scalar_one())

# ---- endpoint ----
@router.post("/contracts/{contract_id}/process", response_model=dict)
async def process_contract_endpoint(
    contract_id: str,
    session: AsyncSession = Depends(get_tidb_session),
    use_llm: bool = Query(True, description="Use the LLM pipeline (default True)"),
    model: Optional[str] = Query(None, description="Override model name, e.g., gpt-4o-mini"),
    batch_size: int = Query(10, ge=1, le=32),
    force: bool = Query(False, description="Re-process even if already processed"),
):
    # 1) Skip if we've processed before (unless force)
    existing = await _get_existing_counts(session, contract_id)
    if (existing["clauses"] > 0 or existing["risks"] > 0) and not force:
        return {
            "contract_id": contract_id,
            "skipped": True,
            "reason": "already_processed",
            **existing,
        }

    # 2) Guard: make sure there are chunks to process
    chunk_count = await _get_chunk_count(session, contract_id)
    if chunk_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No chunks found for this contract. Ingest it before processing.",
        )

    # 3) Process
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

    return {
        "contract_id": contract_id,
        "skipped": False,
        **counts,
    }


# How to call it in Postman
# •	Normal (idempotent) run:
# --	POST http://127.0.0.1:8000/api/v1/contracts/<CONTRACT_ID>/process
# •	Force re-process:
# --	POST http://127.0.0.1:8000/api/v1/contracts/<CONTRACT_ID>/process?force=true
# •	Optional knobs:
# --	?use_llm=false to use the heuristic pipeline
# --	?model=gpt-4o-mini&batch_size=12 if you want overrides


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
