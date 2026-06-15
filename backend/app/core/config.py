from typing import Literal, Optional
from pydantic import field_validator
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

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def validate_jwt_secret_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters long")
        return v

    RESEND_API_KEY: Optional[str] = None
    FROM_EMAIL: str

    OPENAI_API_KEY: Optional[str] = None

    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    AWS_REGION: str = "ap-south-1"
    S3_BUCKET_NAME: str

    LOG_EMAILS_ONLY: bool = False

    APP_URL: str
    PROMETHEUS_MULTIPROC_DIR: str = "/tmp/prometheus"

    GRAFANA_ADMIN_PASSWORD: str | None = None
    GRAFANA_SERVER_ROOT_URL: str | None = None
    GF_SERVER_SERVE_FROM_SUB_PATH: bool = True
    
    ADMIN_TOKEN: str | None = None
    SLACK_WEBHOOK_URL: Optional[str] = None
    ALERT_EMAIL_TO: str | None = None
    EMAIL_FROM_DOMAIN: str | None = None

    MAX_DOCS_PER_USER: int = 20
    MAX_DAILY_TOKENS_PER_USER: int = 100000
    RETRIEVAL_TOP_K: int = 5
    STREAM_CHUNK_TIMEOUT: int = 30
    LOG_FORMAT: Optional[Literal["json", "pretty"]] = None
    MAX_DAILY_QUERIES_PER_USER: int = 500

    model_config = {"env_file": env_file}

settings: Settings = Settings()  # type: ignore[call-arg]
