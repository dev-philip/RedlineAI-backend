# app/models/vector_docs.py
from typing import Any
from sqlalchemy import BigInteger, String, Text, TIMESTAMP, func, event, DDL
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.config import settings
from app.models.sql_types import TiDBVector


class VectorDoc(Base):
    __tablename__ = "vector_docs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Align vector dimension with your global embeddings
    embedding: Mapped[Any] = mapped_column(TiDBVector(settings.embed_dim), nullable=False)

    created_at = mapped_column(TIMESTAMP, server_default=func.current_timestamp(), nullable=False)


# TiDB Serverless requires the expression form + on-demand columnar replica.
event.listen(
    VectorDoc.__table__,
    "after_create",
    DDL("""
        ALTER TABLE vector_docs
          ADD VECTOR INDEX idx_vector_docs_embedding
          ((VEC_COSINE_DISTANCE(embedding)))
          USING HNSW
          ADD_COLUMNAR_REPLICA_ON_DEMAND;
    """),
)
