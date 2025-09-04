# app/services/contract_vector_store.py
from typing import Optional
import urllib.parse
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import TiDBVectorStore
from app.config import settings

from app.db import tidb_sync_engine
from sqlalchemy import text

# One shared embeddings instance
_embeddings = OpenAIEmbeddings(
    model=settings.embed_model,
    api_key=settings.OPENAI_API_KEY,
)

def embed_query(q: str):
    return _embeddings.embed_query(q)

def _sync_connection_string() -> str:
    pwd = urllib.parse.quote_plus(settings.TIDB_PASSWORD)
    qs = "charset=utf8mb4"
    if getattr(settings, "TIDB_SSL_CA", None):
        qs += f"&ssl_ca={urllib.parse.quote_plus(settings.TIDB_SSL_CA)}"
    # pymysql is sync (good for langchain community TiDBVectorStore)
    return (
        f"mysql+pymysql://{settings.TIDB_USER}:{pwd}"
        f"@{settings.TIDB_HOST}:{settings.TIDB_PORT}/{settings.TIDB_DB}?{qs}"
    )

def get_vectorstore() -> TiDBVectorStore:
    """
    Uses the TiDB vector integration's own table (default: tidb_vector_langchain).
    We rely on metadata.contract_id being written during ingestion.
    """
    return TiDBVectorStore(
        connection_string=_sync_connection_string(),
        embedding_function=_embeddings,
        table_name="tidb_vector_langchain",  # keep separate from your contract_chunks
        distance_strategy="cosine",
        # metadata_column_name="meta",  
    )

def insert_contract_row(contract_id: str, tenant: str, doc_type: str, filename: str, sha256: str):
    with tidb_sync_engine.begin() as conn:
        conn.execute(
            text(f"""
                INSERT IGNORE INTO {settings.contracts_table}
                (id, tenant, doc_type, original_filename, sha256)
                VALUES (:id, :tenant, :doc_type, :filename, :sha256)
            """),
            dict(id=contract_id, tenant=tenant, doc_type=doc_type, filename=filename, sha256=sha256),
        )

# ---------- helper queries ----------
def get_contract_id_by_sha(sha256: str, tenant: Optional[str]) -> Optional[str]:
    with tidb_sync_engine.begin() as conn:
        if tenant:
            row = conn.execute(
                text(f"""
                    SELECT id FROM {settings.contracts_table}
                    WHERE sha256 = :sha AND tenant = :tenant
                    LIMIT 1
                """),
                {"sha": sha256, "tenant": tenant},
            ).first()
        else:
            row = conn.execute(
                text(f"""
                    SELECT id FROM {settings.contracts_table}
                    WHERE sha256 = :sha
                    LIMIT 1
                """),
                {"sha": sha256},
            ).first()
    return row[0] if row else None

def contract_exists_by_sha(sha256: str, tenant: Optional[str]) -> bool:
    return get_contract_id_by_sha(sha256, tenant) is not None