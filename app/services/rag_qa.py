# app/services/rag_qa.py
from __future__ import annotations
from typing import List, Dict, Any
import math

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import OpenAIEmbeddings, ChatOpenAI

from app.config import settings
from app.services.contract_vector_store import get_vectorstore

# Local embeddings client (used for MMR rerank)
_embeddings = OpenAIEmbeddings(
    model=settings.embed_model,
    api_key=settings.OPENAI_API_KEY,
)

def _cosine(a: List[float], b: List[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    return num / (da * db) if da and db else 0.0

def _filter_by_contract(docs: List[Document], contract_id: str) -> List[Document]:
    return [d for d in docs if str(d.metadata.get("contract_id")) == str(contract_id)]

def _mmr_rerank(question: str, candidates: List[Document], k: int, lambda_mult: float = 0.5) -> List[Document]:
    """Simple MMR reranker over an already-fetched candidate pool."""
    if not candidates:
        return []

    q_vec = _embeddings.embed_query(question)
    d_vecs = _embeddings.embed_documents([d.page_content for d in candidates])
    q_sims = [_cosine(vec, q_vec) for vec in d_vecs]

    selected: List[int] = []
    remaining = list(range(len(candidates)))

    while remaining and len(selected) < k:
        if not selected:
            # pick most similar to the query
            best = max(remaining, key=lambda i: q_sims[i])
            remaining.remove(best)
            selected.append(best)
            continue

        # compute MMR score for each remaining item
        def max_sim_to_selected(i: int) -> float:
            return max(_cosine(d_vecs[i], d_vecs[j]) for j in selected) if selected else 0.0

        scores = {
            i: lambda_mult * q_sims[i] - (1.0 - lambda_mult) * max_sim_to_selected(i)
            for i in remaining
        }
        best = max(scores, key=scores.get)
        remaining.remove(best)
        selected.append(best)

    return [candidates[i] for i in selected]

def _retrieve(contract_id: str, question: str, k: int = 6, mmr: bool = False) -> List[Document]:
    vs = get_vectorstore()

    # Get a pool (bigger if we plan to MMR)
    pool_k = max(4 * k, 20) if mmr else k

    # Fetch by similarity. (Some backends don’t support server-side metadata filtering;
    # we filter by contract_id in Python to be safe.)
    try:
        candidates = vs.similarity_search(question, k=pool_k)
    except NotImplementedError:
        # Extremely defensive; most backends implement similarity_search.
        candidates = []

    candidates = _filter_by_contract(candidates, contract_id)

    if not mmr:
        return candidates[:k]

    # Fallback MMR rerank
    return _mmr_rerank(question, candidates, k=k)

_prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a precise contract analyst. Answer ONLY from the provided snippets. "
               "Cite using [#] where # is the source index."),
    ("human", "Question:\n{question}\n\nContext snippets:\n{context}\n\n"
              "Return a concise answer with citations like [1], [2]."),
])

def answer_contract_question(contract_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    question: str = (payload or {}).get("question", "")
    k: int = int((payload or {}).get("k", 6))
    mmr: bool = bool((payload or {}).get("mmr", False))  # default False to avoid backend MMR issues

    if not question:
        return {"error": "question is required"}

    docs = _retrieve(contract_id, question, k=k, mmr=mmr)

    # Build a compact, numbered context block
    lines = []
    for i, d in enumerate(docs, start=1):
        m = d.metadata or {}
        src = m.get("source_file") or m.get("original_filename") or "unknown"
        page = m.get("page")
        chunk_idx = m.get("chunk_index")
        header = f"[{i}] {src}" + (f" · p.{page}" if page is not None else "") + (f" · chunk {chunk_idx}" if chunk_idx is not None else "")
        lines.append(f"{header}\n{d.page_content}")
    context = "\n\n---\n".join(lines) if lines else "No relevant context found."

    llm = ChatOpenAI(model="gpt-4o-mini", api_key=settings.OPENAI_API_KEY, temperature=0)
    chain = _prompt | llm | StrOutputParser()
    answer_text = chain.invoke({"question": question, "context": context})

    sources = []
    for i, d in enumerate(docs, start=1):
        m = d.metadata or {}
        sources.append({
            "rank": i,
            "source_file": m.get("source_file") or m.get("original_filename"),
            "page": m.get("page"),
            "chunk_index": m.get("chunk_index"),
            "doc_type": m.get("doc_type"),
            "tenant": m.get("tenant"),
            "tags": m.get("tags"),
            "text": d.page_content[:4000],
        })

    return {
        "contract_id": contract_id,
        "question": question,
        "k": k,
        "mmr": mmr,
        "answer": answer_text,
        "sources": sources,
    }
