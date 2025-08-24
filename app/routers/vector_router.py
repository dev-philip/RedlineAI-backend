from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db import get_tidb_session
from app.schemas.vector_docs import VectorDocCreate, VectorDocOut
from app.embeddings import embed_text

router = APIRouter()

@router.post("/docs", response_model=VectorDocOut, status_code=status.HTTP_201_CREATED)
async def create_doc(payload: VectorDocCreate, db: AsyncSession = Depends(get_tidb_session)):
    basis = f"{payload.title}\n{payload.content}".strip()
    vec = embed_text(basis)

    # TiDB accepts a string literal "[...]" that CASTs to VECTOR
    vec_str = "[" + ",".join(f"{x:.7f}" for x in vec) + "]"

    sql = text("""
        INSERT INTO vector_docs (title, content, embedding)
        VALUES (:title, :content, CAST(:vec AS VECTOR))
    """)
    try:
        await db.execute(sql, {"title": payload.title, "content": payload.content, "vec": vec_str})
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Insert failed: {e}")

    row = await db.execute(text(
        "SELECT id, title, content FROM vector_docs WHERE title=:title ORDER BY id DESC LIMIT 1"
    ), {"title": payload.title})
    r = row.mappings().first()
    return VectorDocOut(**dict(r))

@router.get("/search", response_model=list[VectorDocOut])
async def search_docs(
    q: str = Query(..., description="Free text to embed and search against stored documents"),
    k: int = Query(5, ge=1, le=50),
    db: AsyncSession = Depends(get_tidb_session),
):
    q_vec = embed_text(q)
    q_vec_str = "[" + ",".join(f"{x:.7f}" for x in q_vec) + "]"

    # ANN search (cosine). LIMIT is important for HNSW to be used.
    sql = text("""
        SELECT id, title, content
        FROM vector_docs
        ORDER BY VEC_COSINE_DISTANCE(embedding, CAST(:qvec AS VECTOR))
        LIMIT :k
    """)
    res = await db.execute(sql, {"qvec": q_vec_str, "k": k})
    return [VectorDocOut(**dict(r)) for r in res.mappings().all()]
