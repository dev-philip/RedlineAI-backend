# app/services/contract_query.py
from typing import List, Dict, Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.contract_vector_store import get_vectorstore, embed_query

# ---- RISKS ----
async def list_risks(
    session: AsyncSession,
    contract_id: str,
    min_severity: int = 1,
    clause_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    sql = """
        SELECT r.id, r.severity, r.rule_id, r.rationale, r.suggested_fix,
               c.clause_type, c.chunk_id
        FROM risks r
        JOIN clauses c ON c.id = r.clause_id
        WHERE r.contract_id = :cid
          AND r.severity >= :minsev
    """
    params = {"cid": contract_id, "minsev": min_severity}
    if clause_type:
        sql += " AND c.clause_type = :ctype"
        params["ctype"] = clause_type

    sql += " ORDER BY r.severity DESC, r.id DESC LIMIT 500"
    rows = (await session.execute(text(sql), params)).all()
    return [
        {
            "risk_id": r[0],
            "severity": r[1],
            "rule_id": r[2],
            "rationale": r[3],
            "suggested_fix": r[4],
            "clause_type": r[5],
            "chunk_id": r[6],
        }
        for r in rows
    ]


# ---- QA (vector-only for now; add FTS prefilter later) ----
def qa_vector_search(
    question: str,
    contract_id: str,
    k: int = 6,
    mmr: bool = False,
) -> List[Dict[str, Any]]:
    """
    Searches only within chunks whose metadata.contract_id == <contract_id>.
    """
    vs = get_vectorstore()
    filter_by_contract = {"contract_id": contract_id}

    if mmr:
        docs = vs.max_marginal_relevance_search(
            question, k=k, filter=filter_by_contract
        )
        # MMR usually comes without scores in many vectorstores; normalize:
        return [
            {
                "text": d.page_content,
                "score": None,
                "metadata": dict(d.metadata or {}),
            }
            for d in docs
        ]

    # default: simple similarity
    results = vs.similarity_search_with_score(question, k=k, filter=filter_by_contract)
    return [
        {
            "text": doc.page_content,
            "score": float(score),
            "metadata": dict(doc.metadata or {}),
        }
        for (doc, score) in results
    ]
