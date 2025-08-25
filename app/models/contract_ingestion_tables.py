# app/models/contract_ingestion_tables.py
from sqlalchemy import (
    Column, String, Integer, BigInteger, Text, TIMESTAMP, func,
    ForeignKey, UniqueConstraint, Index, event, DDL
)
from sqlalchemy.dialects.mysql import JSON as MySQLJSON

from app.db import Base
from app.config import settings
from app.models.sql_types import TiDBVector


class Contract(Base):
    """
    One row per uploaded contract (idempotency + audit).
    """
    __tablename__ = settings.contracts_table  # e.g., "contracts"

    id = Column(String(36), primary_key=True)  # UUID string
    tenant = Column(String(255), nullable=True, index=True)
    doc_type = Column(String(64), nullable=True, index=True)
    original_filename = Column(String(512), nullable=False)
    sha256 = Column(String(64), nullable=False)
    uploaded_at = Column(TIMESTAMP, server_default=func.current_timestamp(), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant", "sha256", name="uniq_tenant_sha"),
    )


class ContractChunk(Base):
    """
    One row per text chunk from a contract, with embedding and rich metadata.
    """
    __tablename__ = settings.chunks_table  # e.g., "contract_chunks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    contract_id = Column(
        String(36),
        ForeignKey(f"{settings.contracts_table}.id"),
        index=True,
        nullable=False,
    )

    page = Column(Integer, nullable=True)         # original page (if known)
    chunk_index = Column(Integer, nullable=True)  # order within doc

    content = Column(Text, nullable=False)
    embedding = Column(TiDBVector(settings.embed_dim), nullable=False)  # VECTOR(n)

    # IMPORTANT: don't name this "metadata" (reserved by SQLAlchemy)
    meta_json = Column(MySQLJSON, nullable=True)

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), nullable=False)

    __table_args__ = (
        Index("idx_contract_chunks_contract_page", "contract_id", "page"),
    )


# ---- Vector index for TiDB Serverless ----
# Requires:
#  1) distance expression: ((VEC_COSINE_DISTANCE(embedding)))
#  2) columnar replica: ADD_COLUMNAR_REPLICA_ON_DEMAND
_vector_idx = DDL(f"""
ALTER TABLE {settings.chunks_table}
  ADD VECTOR INDEX idx_{settings.chunks_table}_embedding
  ((VEC_COSINE_DISTANCE(embedding)))
  USING HNSW
  ADD_COLUMNAR_REPLICA_ON_DEMAND;
""")

# This runs only when the table is newly created (safe for restarts)
event.listen(ContractChunk.__table__, "after_create", _vector_idx)
