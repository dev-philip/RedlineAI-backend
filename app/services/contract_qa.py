# app/services/contract_qa.py
from typing import Any, Dict, List, Optional, Tuple
from app.services.contract_vector_store import get_vectorstore

def qa_retrieve(
    question: str,
    contract_id: str,
    k: int = 6,
    mmr: bool = False,
    fetch_k: Optional[int] = None,
    lambda_mult: float = 0.5,
) -> Dict[str, Any]:
    """
    Returns top-K snippets with metadata, restricted to this contract.
    - If mmr=False: uses similarity with scores.
    - If mmr=True:  uses MMR (no scores).
    """
    vs = get_vectorstore()

    # Preferred path: use metadata filter directly
    try:
        if mmr:
            docs = vs.max_marginal_relevance_search(
                question,
                k=k,
                fetch_k=fetch_k or max(k * 4, 20),
                lambda_mult=lambda_mult,
                filter={"contract_id": contract_id},
            )
            results = [
                {
                    "snippet": d.page_content[:600],
                    "metadata": d.metadata,   # includes page, heading, chunk_index, contract_id
                }
                for d in docs
            ]
            return {"contract_id": contract_id, "k": k, "mmr": True, "results": results}
        else:
            pairs: List[Tuple[Any, float]] = vs.similarity_search_with_relevance_scores(
                question,
                k=k,
                filter={"contract_id": contract_id},
            )
            results = [
                {
                    "score": float(score),
                    "snippet": d.page_content[:600],
                    "metadata": d.metadata,
                }
                for (d, score) in pairs
            ]
            return {"contract_id": contract_id, "k": k, "mmr": False, "results": results}
    except Exception:
        # Fallback for older libs that don’t support `filter=`:
        if mmr:
            docs = vs.max_marginal_relevance_search(
                question, k=max(k * 5, 40), fetch_k=max(k * 8, 64), lambda_mult=lambda_mult
            )
            docs = [d for d in docs if d.metadata.get("contract_id") == contract_id][:k]
            results = [{"snippet": d.page_content[:600], "metadata": d.metadata} for d in docs]
            return {"contract_id": contract_id, "k": k, "mmr": True, "results": results}
        else:
            pairs = vs.similarity_search_with_relevance_scores(question, k=max(k * 5, 40))
            filtered = [(d, s) for (d, s) in pairs if d.metadata.get("contract_id") == contract_id][:k]
            results = [
                {"score": float(s), "snippet": d.page_content[:600], "metadata": d.metadata}
                for (d, s) in filtered
            ]
            return {"contract_id": contract_id, "k": k, "mmr": False, "results": results}
