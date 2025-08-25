# app/routers/search.py
from fastapi import APIRouter, Query
from typing import Optional, List, Dict, Any
from app.services.contract_vector_store import get_vectorstore

router = APIRouter()

@router.get("/search")
def search(
    q: str = Query(..., description="Natural language query"),
    tenant: Optional[str] = None,
    contract_id: Optional[str] = None,
    k: int = 3,
):
    vs = get_vectorstore()
    # Build a metadata filter so you can scope to a tenant and/or a single contract
    md: Dict[str, Any] = {}
    if tenant:
        md["tenant"] = tenant
    if contract_id:
        md["contract_id"] = contract_id

    docs = vs.similarity_search(q, k=k, metadata=md if md else None)
    # return minimal fields
    return [
        {
            "content": d.page_content,
            "metadata": d.metadata,
        }
        for d in docs
    ]
