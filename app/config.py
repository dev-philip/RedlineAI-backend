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

    # TiDB
    TIDB_HOST: str
    TIDB_PORT: int
    TIDB_DB: str
    TIDB_USER: str
    TIDB_PASSWORD: str
    TIDB_POOL_SIZE: int
    TIDB_MAX_OVERFLOW: int

    # 🔐 TLS (used in db.py)
    # TIDB_SSL_CA: Optional[str] = "C:\certs\isrgrootx1.pem"
    TIDB_SSL_CA: str
    TIDB_SSL_VERIFY_CERT: bool = True
    TIDB_SSL_VERIFY_IDENTITY: bool = True

    # Google OAuth
    SECRET_KEY: str
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str


    # AWS Credentials for S3 Bucket
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    AWS_DEFAULT_REGION: str
    S3_BUCKET_NAME: str
    S3_PREFIX: str

    #activate schedular 
    RUN_ALERTS_SCHEDULER: str

    langchain_table: str

    # langchain_table: str = "tidb_vector_langchain"
    llm_model_name: str = "gpt-4o-mini"
    policy_text: str = (
        "Our default policy: "
        "- No auto-renew without explicit opt-in or <=30-day termination window.\n"
        "- Liability cap >= fees for 12 months; exclude indirect damages.\n"
        "- Governing law: home jurisdiction preferred.\n"
        "- SLA uptime >= 99.9% with credits.\n"
        "- NDA confidentiality standard; IP remains with owner.\n"
    )


    class Config:
        env_file = ".env"

settings = Settings()
