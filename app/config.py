# app/config.py
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    ENV: str = "development"

    # OpenAI
    OPENAI_API_KEY: str
    embed_model: str = "text-embedding-3-small"  # or -large
    embed_dim: int = 1536                        # 1536 or 3072

    # Table names
    contracts_table: str = "contracts"
    chunks_table: str = "contract_chunks"

    # Redis
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_PASSWORD: str

    # Postgres
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int  # (int is nicer than str)

    # TiDB
    TIDB_HOST: str
    TIDB_PORT: int
    TIDB_DB: str
    TIDB_USER: str
    TIDB_PASSWORD: str
    TIDB_POOL_SIZE: int
    TIDB_MAX_OVERFLOW: int

    # 🔐 TLS (used in db.py)
    TIDB_SSL_CA: Optional[str] = "C:\certs\isrgrootx1.pem"
    TIDB_SSL_VERIFY_CERT: bool = True
    TIDB_SSL_VERIFY_IDENTITY: bool = True

    # Google OAuth
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str

    class Config:
        env_file = ".env"

settings = Settings()
