# app/models/vector_docs.py
from sqlalchemy import BigInteger, String, Text, TIMESTAMP, text, event, DDL
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType
from app.db import Base

class TiDBVector(UserDefinedType):
    cache_ok = True
    def __init__(self, dim: int): self.dim = dim
    def get_col_spec(self, **kw): return f"VECTOR({self.dim})"

VECTOR_DIM = 384  # or 1536 if you use OpenAI embeddings

class VectorDoc(Base):
    __tablename__ = "vector_docs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[bytes] = mapped_column(TiDBVector(VECTOR_DIM), nullable=True)
    created_at = mapped_column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

# Use DDL(), not text()
event.listen(
    VectorDoc.__table__,
    "after_create",
    DDL("""
        CREATE VECTOR INDEX idx_vector_docs_embedding
        ON vector_docs ((VEC_COSINE_DISTANCE(embedding))) USING HNSW;
    """),
)
