from typing import Optional
from pydantic_settings import BaseSettings
import os

env_file = os.getenv("ENV_FILE", ".env.local")

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str = Optional[str]

    JWT_SECRET: str = Optional[str]

    OPENAI_API_KEY: str = Optional[str]

    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    AWS_REGION: str = "ap-south-1"
    S3_BUCKET_NAME: str

    SMTP_HOST: str = Optional[str]
    SMTP_PORT: int = Optional[int]
    SMTP_USER: str = Optional[str]
    SMTP_PASSWORD: str = Optional[str]

    APP_URL: str = Optional[str]

    MAX_DOCS_PER_USER: int = 20
    MAX_DAILY_TOKENS_PER_USER: int = 100000

    model_config = {"env_file": env_file}

settings = Settings()