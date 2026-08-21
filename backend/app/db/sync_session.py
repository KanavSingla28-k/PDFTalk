from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# Strip the async driver prefix — asyncpg is not usable in sync context.
# "postgresql+asyncpg://..." → "postgresql+psycopg://..."
_sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg://")

_engine = create_engine(
    _sync_url,
    pool_size=5,
    max_overflow=2,
    pool_pre_ping=True,
    pool_recycle=3600,
)

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=_engine,
    autocommit=False,
    autoflush=False,
)
