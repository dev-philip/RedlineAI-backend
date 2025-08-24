from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ENV: str = "development"

    # OpenAI Credentials
    OPENAI_API_KEY: str

    # Redis Caching Credentials
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_PASSWORD: str

    # Database Postgres Credentials
    POSTGRES_USER:str
    POSTGRES_PASSWORD:str
    POSTGRES_DB:str
    POSTGRES_HOST:str
    POSTGRES_PORT:str

    # Database TIDB Credentials
    TIDB_HOST:str
    TIDB_PORT:str
    TIDB_DB:str
    TIDB_USER:str
    TIDB_PASSWORD:str
    TIDB_POOL_SIZE:int
    TIDB_MAX_OVERFLOW:int

    # Google Auth Credentials
    GOOGLE_CLIENT_ID:str
    GOOGLE_CLIENT_SECRET:str
    GOOGLE_REDIRECT_URI:str

    class Config:
        env_file = ".env"


settings = Settings()
