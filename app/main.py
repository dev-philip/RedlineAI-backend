# app/main.py
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.shared.errors import AppError
from app.db import tidb_engine as engine, Base, get_tidb_session as get_session
from app import models  # 👈 this pulls in everything under app/models
from app.routers import tidb_router, vector_router


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
api_router.include_router(tidb_router.router, prefix="/tidb", tags=["Test TIDB Database"])
api_router.include_router(vector_router.router, prefix="/vector", tags=["Vector Demo"])
app.include_router(api_router)
