# app/services/ingestion_graph.py
from __future__ import annotations

import uuid
from typing import Any, Dict, List, TypedDict

from langgraph.graph import StateGraph, END
from langchain_core.documents import Document

from app.services.document_loaders import load_any, split_docs, compute_sha256
from app.services.contract_vector_store import (
    get_vectorstore,
    insert_contract_row,
    contract_exists_by_sha,
)

# ---- State ----
class IngestState(TypedDict):
    file_path: str
    meta: Dict[str, Any]          # tenant, doc_type, original_filename, tags, etc.
    sha256: str
    contract_id: str
    docs: List[Document]
    chunks: List[Document]
    stored_ids: List[str]
    skipped: bool                 # true if duplicate


# ---- Nodes ----
def register_or_skip(state: IngestState) -> IngestState:
    sha = compute_sha256(state["file_path"])
    state["sha256"] = sha

    tenant = state["meta"].get("tenant")
    if contract_exists_by_sha(sha, tenant):
        state["skipped"] = True
        return state

    contract_id = str(uuid.uuid4())
    state["contract_id"] = contract_id

    insert_contract_row(
        contract_id=contract_id,
        tenant=tenant,
        doc_type=state["meta"].get("doc_type"),
        filename=(
            state["meta"].get("original_filename")
            or state["meta"].get("source_file")
            or state["file_path"].split("/")[-1]
        ),
        sha256=sha,
    )
    state["skipped"] = False
    return state


def load_file(state: IngestState) -> IngestState:
    if state.get("skipped"):
        return state

    # Base metadata attached to every loaded page/document
    base_meta = dict(state["meta"])
    base_meta["contract_id"] = state["contract_id"]
    base_meta["sha256"] = state["sha256"]
    base_meta.setdefault("original_filename", base_meta.get("source_file"))
    if base_meta.get("tags") is None:
        base_meta["tags"] = []

    docs = load_any(
        state["file_path"],
        base_metadata=base_meta,
        ocr_if_needed=True,
    )
    state["docs"] = docs
    return state


def chunk(state: IngestState) -> IngestState:
    if state.get("skipped"):
        return state
    # ✅ use the right parameter names for your helper
    chunks = split_docs(state["docs"], chunk_size=800, chunk_overlap=120)

    # Ensure every chunk has an index and required metadata
    enriched: List[Document] = []
    for i, ch in enumerate(chunks):
        md = dict(ch.metadata or {})
        md.setdefault("chunk_index", i)
        md.setdefault("contract_id", state["contract_id"])
        md.setdefault("sha256", state["sha256"])
        md.setdefault("tenant", state["meta"].get("tenant"))
        md.setdefault("doc_type", state["meta"].get("doc_type"))
        md.setdefault("original_filename", state["meta"].get("original_filename"))
        md.setdefault("tags", state["meta"].get("tags", []) or [])
        enriched.append(Document(page_content=ch.page_content, metadata=md))

    state["chunks"] = enriched
    return state


def embed_store(state: IngestState) -> IngestState:
    if state.get("skipped"):
        return state

    # Final guard to ensure metadata keys exist on every chunk
    enforced_chunks: List[Document] = []
    for i, ch in enumerate(state["chunks"]):
        md = dict(ch.metadata or {})
        md.setdefault("chunk_index", i)
        md.setdefault("contract_id", state["contract_id"])
        md.setdefault("sha256", state["sha256"])
        md.setdefault("tenant", state["meta"].get("tenant"))
        md.setdefault("doc_type", state["meta"].get("doc_type"))
        md.setdefault("original_filename", state["meta"].get("original_filename"))
        md.setdefault("tags", state["meta"].get("tags", []) or [])
        enforced_chunks.append(Document(page_content=ch.page_content, metadata=md))

    vs = get_vectorstore()
    # TiDBVectorStore stores Document.metadata into the `meta` JSON column
    ids = vs.add_documents(enforced_chunks)

    state["stored_ids"] = ids
    state["chunks"] = enforced_chunks
    return state


def complete(state: IngestState) -> IngestState:
    return state


def build_ingest_graph():
    g = StateGraph(IngestState)
    g.add_node("register_or_skip", register_or_skip)
    g.add_node("load_file", load_file)
    g.add_node("chunk", chunk)
    g.add_node("embed_store", embed_store)
    g.add_node("complete", complete)

    g.set_entry_point("register_or_skip")
    g.add_edge("register_or_skip", "load_file")
    g.add_edge("load_file", "chunk")
    g.add_edge("chunk", "embed_store")
    g.add_edge("embed_store", "complete")
    g.add_edge("complete", END)

    return g.compile()
