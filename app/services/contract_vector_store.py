# app/services/contract_vector_store.py
from typing import Optional
import urllib.parse

from sqlalchemy import text

from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import TiDBVectorStore

from app.config import settings
from app.db import tidb_sync_engine


# ----- Embeddings (one shared instance) -----
_embeddings = OpenAIEmbeddings(
    model=settings.embed_model,
    api_key=settings.OPENAI_API_KEY,
)

def embed_query(q: str):
    return _embeddings.embed_query(q)


# ----- Build a sync DSN for TiDBVectorStore -----
def _sync_connection_string() -> str:
    pwd = urllib.parse.quote_plus(settings.TIDB_PASSWORD)
    qs = "charset=utf8mb4"
    if getattr(settings, "TIDB_SSL_CA", None):
        qs += f"&ssl_ca={urllib.parse.quote_plus(settings.TIDB_SSL_CA)}"
    return (
        f"mysql+pymysql://{settings.TIDB_USER}:{pwd}"
        f"@{settings.TIDB_HOST}:{settings.TIDB_PORT}/{settings.TIDB_DB}?{qs}"
    )


# ----- Vector store factory (handles both API variants) -----
def get_vectorstore() -> TiDBVectorStore:
    """
    Returns a TiDB-backed vector store. Tries the 'embedding_function' kwarg first
    (required by some versions), then falls back to 'embedding' (used by others).
    Keep kwargs minimal to avoid base-class **kwargs errors.
    """
    table_name = getattr(settings, "langchain_table", "tidb_vector_langchain")
    conn = _sync_connection_string()

    # Try the variant that your error indicates is required
    try:
        return TiDBVectorStore(
            embedding_function=_embeddings,   # <-- primary path
            connection_string=conn,
            table_name=table_name,
        )
    except TypeError:
        # Fallback for older/newer releases that use 'embedding'
        return TiDBVectorStore(
            connection_string=conn,
            embedding=_embeddings,            # <-- fallback path
            table_name=table_name,
        )


# ----- Contract helpers -----
def insert_contract_row(
    contract_id: str,
    tenant: Optional[str],
    doc_type: Optional[str],
    filename: str,
    sha256: str,
) -> None:
    with tidb_sync_engine.begin() as conn:
        conn.execute(
            text(f"""
                INSERT IGNORE INTO {settings.contracts_table}
                (id, tenant, doc_type, original_filename, sha256)
                VALUES (:id, :tenant, :doc_type, :filename, :sha256)
            """),
            {
                "id": contract_id,
                "tenant": tenant,
                "doc_type": doc_type,
                "filename": filename,
                "sha256": sha256,
            },
        )


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