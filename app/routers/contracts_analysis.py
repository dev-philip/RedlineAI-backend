# app/routers/contracts_analysis.py
from typing import Any, Dict, Optional, Annotated, List
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db import get_tidb_session
from app.services.contract_processing import process_contract
# from app.services.contract_query import list_risks, qa_vector_search
from app.services.contract_qa import qa_retrieve
from app.services.contract_query import qa_vector_search
from app.services.contract_processing import list_risks
from app.services.contract_summary import build_contract_summary

router = APIRouter()

# ----- Risks -----
# @router.get("/contracts/{contract_id}/risks", response_model=list[dict])
# async def get_contract_risks(
#     contract_id: str,
#     session: Annotated[AsyncSession, Depends(get_tidb_session)],
#     min_severity: int = Query(1, ge=1, le=10),
#     clause_type: Optional[str] = Query(None),
# ):
#     """
#     Returns risks for a contract. If you don't have a 'risks' table yet,
#     this will just return an empty list.
#     """
#     query = """
#         SELECT
#           risk_id, doc_id, clause_id, severity, rule_id, rationale, suggested_fix
#         FROM risks
#         WHERE doc_id = :doc_id AND severity >= :sev
#     """
#     params = {"doc_id": contract_id, "sev": min_severity}
#     if clause_type:
#         query += " AND clause_type = :ctype"
#         params["ctype"] = clause_type

#     try:
#         rs = await session.execute(text(query), params)
#         return [dict(r) for r in rs.mappings().all()]
#     except Exception:
#         # If table doesn't exist yet, don't crash the app
#         return []


# ----- Risks -----
@router.get("/contracts/{contract_id}/risks", response_model=List[Dict[str, Any]])
async def list_risks_endpoint(
    contract_id: str,
    min_severity: int = Query(1, ge=0, le=10),
    clause_type: Optional[str] = Query(None),
    session: Annotated[AsyncSession, Depends(get_tidb_session)] = None,
):
    """
    Returns up to 500 risks for a contract, sorted by severity desc.
    Optional: filter by clause_type.
    Includes snippet + (page, heading, chunk_index) from tidb_vector_langchain.meta.
    """
    return await list_risks(session, contract_id, min_severity, clause_type)

# ----- Process -----
@router.post("/contracts/{contract_id}/process", response_model=Dict[str, Any])
async def process_contract_endpoint(
    contract_id: str,
    session: Annotated[AsyncSession, Depends(get_tidb_session)],
):
    counts = await process_contract(session, contract_id)
    return {"contract_id": contract_id, **counts}

# ----- QA -----
@router.post("/contracts/{contract_id}/qa/new", response_model=Dict[str, Any])
async def qa_contract_endpoint(
    contract_id: str,
    body: Dict[str, Any],
):
    question: str = body.get("question", "")
    k: int = int(body.get("k", 6))
    mmr: bool = bool(body.get("mmr", False))
    if not question:
        return {"contract_id": contract_id, "matches": []}
    matches = qa_vector_search(question, contract_id, k=k, mmr=mmr)
    return {"contract_id": contract_id, "matches": matches}


@router.post("/contracts/{contract_id}/qa/best", response_model=Dict[str, Any])
async def contract_qa_endpoint(
    contract_id: str,
    payload: Dict[str, Any] = Body(...),
    session: Annotated[AsyncSession, Depends(get_tidb_session)] = None,  # kept for symmetry / future logging
):
    question: str = payload.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="'question' is required")

    k: int = int(payload.get("k", 6))
    mmr: bool = bool(payload.get("mmr", False))
    fetch_k: Optional[int] = payload.get("fetch_k")
    lambda_mult: float = float(payload.get("lambda_mult", 0.5))

    # Retrieval is sync; we just call it
    out = qa_retrieve(question, contract_id, k=k, mmr=mmr, fetch_k=fetch_k, lambda_mult=lambda_mult)
    return out



@router.get("/contracts/{contract_id}/summary", response_model=Dict[str, Any])
async def contract_summary_endpoint(
    contract_id: str,
    session: AsyncSession = Depends(get_tidb_session),
):
    return await build_contract_summary(session, contract_id)

# # ----- Process (stub) -----
# @router.post("/contracts/{contract_id}/process", response_model=dict)
# async def process_contract(
#     contract_id: str,
#     session: Annotated[AsyncSession, Depends(get_tidb_session)],
# ):
#     # Wire up your actual processing pipeline here
#     return {"contract_id": contract_id, "clauses": 0, "risks": 0}

# ----- QA (stub) -----
# @router.post("/contracts/{contract_id}/qa", response_model=dict)
# async def contract_qa(
#     contract_id: str,
#     payload: dict,
#     session: Annotated[AsyncSession, Depends(get_tidb_session)],
# ):
#     # Replace with real hybrid search + answer
#     return {"contract_id": contract_id, "question": payload.get("question"), "answers": []}
