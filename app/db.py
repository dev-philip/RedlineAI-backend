# app/db.py
import ssl
import urllib.parse
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy import create_engine as create_sync_engine  # NEW
from app.config import settings

class Base(DeclarativeBase):
    pass

# ---------- ASYNC (unchanged) ----------
def _tidb_async_url() -> str:
    if not all([settings.TIDB_HOST, settings.TIDB_DB, settings.TIDB_USER, settings.TIDB_PASSWORD]):
        raise RuntimeError("TiDB env vars are missing. Check TIDB_* in your .env.")
    pwd = urllib.parse.quote_plus(settings.TIDB_PASSWORD)
    return (
        f"mysql+asyncmy://{settings.TIDB_USER}:{pwd}"
        f"@{settings.TIDB_HOST}:{settings.TIDB_PORT}/{settings.TIDB_DB}"
        f"?charset=utf8mb4"
    )

def _tls_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if settings.TIDB_SSL_CA:
        ctx.load_verify_locations(cafile=settings.TIDB_SSL_CA)
    ctx.check_hostname = bool(settings.TIDB_SSL_VERIFY_IDENTITY)
    ctx.verify_mode = ssl.CERT_REQUIRED if settings.TIDB_SSL_VERIFY_CERT else ssl.CERT_NONE
    return ctx

tidb_engine: AsyncEngine = create_async_engine(
    _tidb_async_url(),
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=int(settings.TIDB_POOL_SIZE),
    max_overflow=int(settings.TIDB_MAX_OVERFLOW),
    connect_args={"ssl": _tls_context()},
)

TidbSessionLocal = sessionmaker(bind=tidb_engine, class_=AsyncSession, expire_on_commit=False)

async def get_tidb_session() -> AsyncGenerator[AsyncSession, None]:
    async with TidbSessionLocal() as session:
        yield session

# ---------- SYNC (NEW) ----------
def _tidb_sync_url() -> str:
    """
    Build a mysql+pymysql URL with TLS query args (works well on Windows).
    """
    user = urllib.parse.quote_plus(settings.TIDB_USER)
    pwd = urllib.parse.quote_plus(settings.TIDB_PASSWORD)
    host = settings.TIDB_HOST
    port = settings.TIDB_PORT
    db   = settings.TIDB_DB

    q = {"charset": "utf8mb4"}
    if settings.TIDB_SSL_CA:
        # TiDB Cloud accepts these query params with PyMySQL
        q["ssl_ca"] = settings.TIDB_SSL_CA
        q["ssl_verify_cert"] = "true" if settings.TIDB_SSL_VERIFY_CERT else "false"
        q["ssl_verify_identity"] = "true" if settings.TIDB_SSL_VERIFY_IDENTITY else "false"

    qs = urllib.parse.urlencode(q, safe="/:\\")  # keep Windows paths intact
    return f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{db}?{qs}"

tidb_sync_engine = create_sync_engine(
    _tidb_sync_url(),
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=int(settings.TIDB_POOL_SIZE),
    max_overflow=int(settings.TIDB_MAX_OVERFLOW),
)
