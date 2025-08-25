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

    # Base metadata that will be attached to every page/doc
    base_meta = dict(state["meta"])
    base_meta["contract_id"] = state["contract_id"]
    base_meta.setdefault("original_filename", base_meta.get("source_file"))

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
    # ~800/120 is a solid default for RAG on contracts
    state["chunks"] = split_docs(state["docs"], chunk_size=800, chunk_overlap=120)
    return state


def embed_store(state: IngestState) -> IngestState:
    if state.get("skipped"):
        return state
    vs = get_vectorstore()
    # Stores content + embedding + metadata (DB column name is "metadata")
    ids = vs.add_documents(state["chunks"])
    state["stored_ids"] = ids
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
