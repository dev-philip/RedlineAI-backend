# app/services/contract_vector_store.py
import urllib.parse
from typing import Optional

from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import TiDBVectorStore
from sqlalchemy import text

from app.config import settings
from app.db import tidb_sync_engine


def _tidb_sync_connection_string() -> str:
    user = urllib.parse.quote_plus(settings.TIDB_USER)
    pwd  = urllib.parse.quote_plus(settings.TIDB_PASSWORD)
    host = settings.TIDB_HOST
    port = settings.TIDB_PORT
    db   = settings.TIDB_DB

    q = {"charset": "utf8mb4"}
    if settings.TIDB_SSL_CA:
        q["ssl_ca"] = settings.TIDB_SSL_CA
        q["ssl_verify_cert"] = "true" if settings.TIDB_SSL_VERIFY_CERT else "false"
        q["ssl_verify_identity"] = "true" if settings.TIDB_SSL_VERIFY_IDENTITY else "false"

    qs = urllib.parse.urlencode(q, safe="/:\\")
    return f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{db}?{qs}"


_embeddings = OpenAIEmbeddings(
    model=settings.embed_model,
    api_key=settings.OPENAI_API_KEY,
)

def get_vectorstore() -> TiDBVectorStore:
    conn = _tidb_sync_connection_string()
    try:
        # Older LC versions: positional signature
        return TiDBVectorStore(conn, _embeddings)
    except (TypeError, ImportError):
        # Newer LC versions: keyword signature
        return TiDBVectorStore(
            connection_string=conn,
            embedding=_embeddings,
            # table_name="tidb_vector_langchain",
            table_name="contract_chunks_vector", 
            distance_strategy="cosine",
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
