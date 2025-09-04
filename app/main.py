# app/main.py
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.shared.errors import AppError
from app.db import tidb_engine as engine, Base, get_tidb_session as get_session
from app import models  # 👈 this pulls in everything under app/models
from app.routers import tidb_router, vector_router, s3_router, auth_router, contracts_analysis_llm, alerts
from app.routers.ingest import router as ingest_router  # 👈 NEW
from app.routers import contracts_analysis  # add import
from app.routers import search as search_router


# import os
# from apscheduler.schedulers.asyncio import AsyncIOScheduler
# from app.db import async_session_factory
# from app.services.alert_dispatcher import run_alerts_once


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- Startup: create tables (quick start; use Alembic in prod) ----
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(">>> TiDB startup complete (tables ensured)")   # 👈 sanity print
    yield  # ---- App runs ----

    # ---- Shutdown: dispose engine ----
    await engine.dispose()
    print(">>> TiDB engine disposed")   # 👈 optional shutdown print

# Initialize app with lifespan (replaces deprecated @app.on_event)
app = FastAPI(
    title="FastAPI + MySQL (TiDB) Starter",
    description="A sample FastAPI app with TiDB (MySQL protocol) and modular structure",
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


# scheduler = AsyncIOScheduler()

# async def _alerts_job():
#     async with async_session_factory() as session:
#         await run_alerts_once(session)

# @app.on_event("startup")
# async def on_startup():
#     # Only start the scheduler if explicitly enabled (avoid dup in --reload or multi-workers)
#     if os.getenv("RUN_ALERTS_SCHEDULER", "0") == "1":
#         scheduler.add_job(
#             _alerts_job,
#             "interval",
#             seconds=60,
#             id="alerts-job",
#             max_instances=1,
#             coalesce=True,
#         )
#         scheduler.start()

# @app.on_event("shutdown")
# async def on_shutdown():
#     if os.getenv("RUN_ALERTS_SCHEDULER", "0") == "1":
#         scheduler.shutdown(wait=False)

# Root
@app.get("/")
def read_root():
    return {"message": "Welcome to FastAPI + TiDB 🚀"}

# Health (useful for containers/load balancers)
@app.get("/health")
async def health():
    return {"status": "ok"}

# API router
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router.router, prefix="/auth", tags=["Auth"])
api_router.include_router(contracts_analysis_llm.router, prefix="/llm", tags=["LLM Process"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["Test Alert"])
api_router.include_router(tidb_router.router, prefix="/tidb", tags=["Test TIDB Database"])
api_router.include_router(vector_router.router, prefix="/vector", tags=["Vector Demo"])
api_router.include_router(s3_router.router, prefix="/s3", tags=["Aws S3 bucket"])
api_router.include_router(ingest_router)  # 👈 NEW => /api/v1/ingest
api_router.include_router(search_router.router, prefix="/search", tags=["Search"])
api_router.include_router(contracts_analysis.router, tags=["Contracts"])
app.include_router(api_router)
