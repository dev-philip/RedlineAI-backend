# app/routers/ingest.py
import os
import uuid
import shutil
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, UploadFile, File, Form
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.schemas.ingestion import IngestResponse
from app.services.ingestion_graph import build_ingest_graph

router = APIRouter(tags=["ingestion"])

# Where uploaded files are temporarily staged before parsing
INGEST_DIR = "/tmp/redline_ingest"
os.makedirs(INGEST_DIR, exist_ok=True)

# Build the LangGraph once per process
graph = build_ingest_graph()


@router.post("/ingest", response_model=List[IngestResponse])
async def ingest_files(
    files: List[UploadFile] = File(...),
    doc_type: Optional[str] = Form(default=None),
    tenant: Optional[str] = Form(default=None),
    tags: Optional[str] = Form(default=None),
):
    results: List[IngestResponse] = []

    for f in files:
        tmp_name = f"{uuid.uuid4()}_{f.filename}"
        tmp_path = os.path.join(INGEST_DIR, tmp_name)
        with open(tmp_path, "wb") as out:
            shutil.copyfileobj(f.file, out)

        meta: Dict[str, Any] = {
            "original_filename": f.filename,
            "doc_type": doc_type,
            "tenant": tenant,
            "tags": [t.strip() for t in (tags.split(",") if tags else [])],
        }

        # Seed the graph state
        state = {
            "file_path": tmp_path,
            "meta": meta,
            "sha256": "",
            "contract_id": "",
            "docs": [],
            "chunks": [],
            "stored_ids": [],
            "skipped": False,
        }

        final_state = await run_in_threadpool(graph.invoke, state)

        results.append(
            IngestResponse(
                file_name=f.filename,
                contract_id=final_state.get("contract_id"),
                sha256=final_state.get("sha256"),
                chunks=len(final_state.get("chunks", [])),
                stored_ids=final_state.get("stored_ids", []),
                metadata=meta,
                skipped=final_state.get("skipped", False),
            )
        )

        # Optional cleanup:
        # os.remove(tmp_path)

    return results
