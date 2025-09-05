# app/main.py
from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.shared.errors import AppError
from app.db import tidb_engine as engine, Base, async_session_maker
from app import models  # 👈 this pulls in everything under app/models
from app.routers import (
    health,
    tidb_router,
    vector_router,
    s3_router,
    auth_router,
    contracts_analysis_llm,
    alerts,
    users,
)
from app.routers.ingest import router as ingest_router
from app.routers import contracts_analysis
from app.routers import search as search_router
from app.services.alert_dispatcher import run_alerts_once

from datetime import datetime
from zoneinfo import ZoneInfo


# -------- Scheduled job --------
async def _alerts_job():
    # Current run start time (UTC)
    started_at_utc = datetime.now(tz=ZoneInfo("UTC"))

    # Pull the next run time from APScheduler (if available)
    scheduler = getattr(app.state, "scheduler", None)
    job = scheduler.get_job("alerts-job") if scheduler else None
    next_run_at_utc = job.next_run_time if job else None  # usually already set to "next"

    # Do the work
    async with async_session_maker() as session:
        sent = await run_alerts_once(
            session,
            run_started_at_utc=started_at_utc,
            next_run_at_utc=next_run_at_utc,
        )

    # Optional: structured log as well
    logger.info(
        "alerts-job finished: ran_at_local=%s sent=%d next_run_local=%s",
        started_at_utc.astimezone(ZoneInfo("America/New_York")).isoformat(),
        sent,
        (next_run_at_utc.astimezone(ZoneInfo("America/New_York")).isoformat()
         if next_run_at_utc else "n/a"),
    )


# -------- Lifespan (startup/shutdown) --------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables (quick start; use Alembic in prod)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(">>> TiDB startup complete (tables ensured)")

    # Start scheduler only when explicitly enabled
    scheduler = None
    if os.getenv("RUN_ALERTS_SCHEDULER", "0") == "1":
        scheduler = AsyncIOScheduler()  # e.g. AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(
            _alerts_job,
            "interval",
            seconds=60,
            id="alerts-job",
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        app.state.scheduler = scheduler  # optional: access elsewhere

    try:
        yield  # ---- App runs ----
    finally:
        # Shutdown: stop scheduler (if running) and dispose engine
        if scheduler:
            scheduler.shutdown(wait=False)
        await engine.dispose()
        print(">>> TiDB engine disposed")


# -------- App --------
app = FastAPI(
    title="Redline AI > The Agentic Contract & SLA Copilot",
    description=(
        "Redline AI is an agentic copilot that ingests contracts, tags clauses, "
        "compares them to company policy & past negotiations (via TiDB Serverless + vector search), "
        "auto-scores risk, drafts redlines, alerts stakeholders, and tracks obligations—end-to-end"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS (tighten in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # e.g., ["https://www.devphilip.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Error handlers
@app.exception_handler(AppError)
async def app_exception_handler(_: Request, err: AppError):
    return JSONResponse(status_code=err.status_code, content={"detail": err.message})

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Error occurred on path {request.url.path}: {str(exc)}")
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred. Please try again later."})

# Root
@app.get("/")
def read_root():
    return {"message": "Welcome to Redline AI🚀"}

# API router
api_router = APIRouter(prefix="/api/v1")
app.include_router(health.router, prefix="/system", tags=["System Health"])
api_router.include_router(auth_router.router, prefix="/auth", tags=["Auth"])
api_router.include_router(ingest_router)  # => /api/v1/ingest
app.include_router(users.router)
api_router.include_router(s3_router.router, prefix="/s3", tags=["Aws S3 bucket"])
api_router.include_router(contracts_analysis_llm.router, prefix="/llm", tags=["LLM Process"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["Test Alert"])
api_router.include_router(tidb_router.router, prefix="/tidb", tags=["Test TIDB Database"])
api_router.include_router(vector_router.router, prefix="/vector", tags=["Vector Demo"])
api_router.include_router(search_router.router, prefix="/search", tags=["Search"])
api_router.include_router(contracts_analysis.router, tags=["Contracts"])
app.include_router(api_router)
