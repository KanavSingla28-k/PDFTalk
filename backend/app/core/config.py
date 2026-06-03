from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = Optional[str]
    REDIS_URL: str = Optional[str]

    JWT_SECRET: str = Optional[str]

    OPENAI_API_KEY: str = Optional[str]

    AWS_ACCESS_KEY_ID: str = Optional[str]
    AWS_SECRET_ACCESS_KEY: str = Optional[str]
    S3_BUCKET_NAME: str = Optional[str]

    SMTP_HOST: str = Optional[str]
    SMTP_PORT: int = Optional[int]
    SMTP_USER: str = Optional[str]
    SMTP_PASSWORD: str = Optional[str]

    APP_URL: str = Optional[str]

    MAX_DOCS_PER_USER: int = 20
    MAX_DAILY_TOKENS_PER_USER: int = 100000

    class Config:
        env_file = ".env.local"

settings = Settings()