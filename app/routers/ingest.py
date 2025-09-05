# app/routers/ingest.py
# 13s is pretty normal for “save → parse → chunk → embed → write,
import os
import uuid
import shutil
from typing import List, Optional, Dict, Any, Annotated

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.schemas.ingestion import IngestResponse
from app.services.ingestion_graph import build_ingest_graph

from app.db import get_tidb_session
from app.services.rag_qa import answer_contract_question


from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession


from sqlalchemy.exc import IntegrityError
from app.db import get_db
from app.repositories.user_repo import UserRepository
from app.schemas.user import UserCreate, UserCreateResponse

from app.services.s3_service import S3Service
from app.dependencies import get_s3_service
from app.repositories.contracts_repo import update_contract_file_url_and_user


router = APIRouter(tags=["Ingestion"])

# Where uploaded files are temporarily staged before parsing
INGEST_DIR = "/tmp/redline_ingest"
os.makedirs(INGEST_DIR, exist_ok=True)

# Build the LangGraph once per process
graph = build_ingest_graph()


@router.post(
"/ingest", 
response_model=List[IngestResponse], 
summary="Ingest new data", 
description="""
Ingest (PDF parse + chunk + embed + DB + S3)
""")
async def ingest_files(
    files: List[UploadFile] = File(...),
    doc_type: Optional[str] = Form(default=None),
    tenant: Optional[str] = Form(default=None),
    tags: Optional[str] = Form(default=None),

    # accept auth-ish hints from the client (for now)
    is_logged_in: bool = Form(default=False),
    user_id: Optional[int] = Form(default=None),

    # deps
    s3: S3Service = Depends(get_s3_service),
    session: AsyncSession = Depends(get_tidb_session),
):
    """
    - Always runs the ingestion graph (register/skip, load, chunk, embed).
    - Only uploads to S3 and updates the `contracts` row if:
        is_logged_in is True AND user_id is provided AND this ingest wasn't skipped.
    """
    results: List[IngestResponse] = []

    for f in files:
        # 1) Write a temp file for the ingestion pipeline
        tmp_name = f"{uuid.uuid4()}_{f.filename}"
        tmp_path = os.path.join(INGEST_DIR, tmp_name)
        with open(tmp_path, "wb") as out:
            shutil.copyfileobj(f.file, out)

        # 2) Prepare base metadata for the graph
        meta: Dict[str, Any] = {
            "original_filename": f.filename,
            "doc_type": doc_type,
            "tenant": tenant,
            "tags": [t.strip() for t in (tags.split(",") if tags else [])],
        }

        # graph state
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

        # 3) Run ingestion (register/skip, load, chunk, embed)
        final_state = await run_in_threadpool(graph.invoke, state)

        contract_id = final_state.get("contract_id")
        skipped = bool(final_state.get("skipped"))
        sha256 = final_state.get("sha256")

        # 4) Optional S3 upload + DB update (only if logged in AND user_id is provided)
        s3_key: Optional[str] = None
        if not skipped and contract_id and is_logged_in and user_id is not None:
            try:
                # Reset the UploadFile stream and upload the original bytes
                await f.seek(0)
                upload_result = await s3.upload_fileobj(
                    file=f,
                    filename=f.filename,
                    content_type=f.content_type or "application/octet-stream",
                )
                # Your service returns: {bucket, key, region, url, content_type}
                s3_key = upload_result.get("key")
                meta["file_url"] = s3_key  # reflect in response metadata
            except ValueError as ve:
                # E.g., file too large
                raise HTTPException(status_code=413, detail=str(ve))
            except Exception as e:
                # Surface S3 error but don't nuke the ingested contract
                raise HTTPException(status_code=500, detail=f"S3 error: {e}")

            # 5) Update contracts.file_url and contracts.user_id
            if s3_key:
                await update_contract_file_url_and_user(
                    session=session,
                    contract_id=contract_id,
                    file_key=s3_key,
                    user_id=user_id,
                )

        # 6) Build API response
        results.append(
            IngestResponse(
                file_name=f.filename,
                contract_id=contract_id,
                sha256=sha256,
                chunks=len(final_state.get("chunks", [])),
                stored_ids=final_state.get("stored_ids", []),
                metadata=meta,
                skipped=skipped,
            )
        )

        # 7) Optional: remove tmp
        # try:
        #     os.remove(tmp_path)
        # except Exception:
        #     pass

    return results


class QARequest(BaseModel):
    question: str
    k: int = 6
    mmr: bool = True


@router.post("/contracts/{contract_id}/qa", response_model=dict)
async def contract_qa(contract_id: str, payload: dict):
    # Wrap in lambda so the thread gets zero extra args
    return await run_in_threadpool(lambda: answer_contract_question(contract_id, payload))


@router.post("/users", response_model=UserCreateResponse, status_code=201)
async def create_user(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    repo = UserRepository(db)
    try:
        user = await repo.create(payload)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # email/google_id are unique; return a helpful error
        raise HTTPException(status_code=409, detail="User with this email or google_id already exists")

    # id is int now — no str() conversion
    return UserCreateResponse(id=user.id, email=user.email, name=user.name)