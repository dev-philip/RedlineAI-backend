# app/db.py
import ssl
import urllib.parse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, AsyncEngine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings

class Base(DeclarativeBase):
    pass

def _tidb_url() -> str:
    # Validate early
    if not all([settings.TIDB_HOST, settings.TIDB_DB, settings.TIDB_USER, settings.TIDB_PASSWORD]):
        raise RuntimeError("TiDB env vars are missing. Check TIDB_* in your .env.")
    pwd = urllib.parse.quote_plus(settings.TIDB_PASSWORD)
    # NOTE: no '?ssl=true' here; we'll pass SSL via connect_args
    return (
        f"mysql+asyncmy://{settings.TIDB_USER}:{pwd}"
        f"@{settings.TIDB_HOST}:{settings.TIDB_PORT}/{settings.TIDB_DB}"
        f"?charset=utf8mb4"
    )

# Create a default TLS context (required by TiDB Serverless)
_ssl_ctx = ssl.create_default_context()  # validates certs by default

tidb_engine: AsyncEngine = create_async_engine(
    _tidb_url(),
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=int(settings.TIDB_POOL_SIZE),
    max_overflow=int(settings.TIDB_MAX_OVERFLOW),
    connect_args={"ssl": _ssl_ctx},  # <— the important part
)

TidbSessionLocal = sessionmaker(bind=tidb_engine, class_=AsyncSession, expire_on_commit=False)

async def get_tidb_session() -> AsyncSession:
    async with TidbSessionLocal() as session:
        yield session
