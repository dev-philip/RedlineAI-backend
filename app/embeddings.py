from functools import lru_cache
from sentence_transformers import SentenceTransformer

@lru_cache(maxsize=1)
def _model():
    # 384-dim, fast + small
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def embed_text(text: str) -> list[float]:
    # normalize embeddings for cosine distance
    vec = _model().encode(text, normalize_embeddings=True)
    return vec.tolist()
