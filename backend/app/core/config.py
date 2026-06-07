from typing import Optional
from pydantic_settings import BaseSettings
import os

env_file = os.getenv("ENV_FILE", ".env.local")

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    RESEND_API_KEY: Optional[str] = None
    FROM_EMAIL: str

    OPENAI_API_KEY: Optional[str] = None

    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    AWS_REGION: str = "ap-south-1"
    S3_BUCKET_NAME: str

    SMTP_HOST: Optional[str] = None
    SMTP_PORT: Optional[int] = None
    SMTP_USER:Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None

    APP_URL: str

    MAX_DOCS_PER_USER: int = 20
    MAX_DAILY_TOKENS_PER_USER: int = 100000
    RETRIEVAL_TOP_K: int = 5
    STREAM_CHUNK_TIMEOUT: int = 30

    model_config = {"env_file": env_file}

settings = Settings()