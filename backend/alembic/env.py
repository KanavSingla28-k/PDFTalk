import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context
from app.core.config import settings

# Make sure our backend package is on the path so imports work
# whether you run alembic from backend/ or from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# --- Import all models so Base.metadata is fully populated ---
# Alembic compares Base.metadata against the live DB to generate diffs.
# If a model isn't imported here, Alembic won't know the table exists
# and will generate a DROP TABLE migration for it.
from app.db import Base  # noqa: F401 — side-effect import populates metadata
from app.models import User, Chunk, Document, JobLog, RefreshToken, EmailVerification

# --- Alembic config object ---
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# This is what --autogenerate diffs against.
target_metadata = Base.metadata

# --- DB URL: prefer environment variable over alembic.ini ---
# In production/CI, set DATABASE_URL in the environment.
# In local dev, it falls back to alembic.ini's sqlalchemy.url.
# Use the synchronous psycopg2 URL here — Alembic doesn't use asyncpg.
# asyncpg URL format:  postgresql+asyncpg://user:pass@host/db
# Alembic URL format:  postgresql+psycopg2://user:pass@host/db  (or just postgresql://)
def get_url() -> str:
    url = settings.DATABASE_URL
    if url.startswith("postgresql+asyncpg://"):
        # Alembic needs a synchronous driver; swap the driver prefix
        url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    return url or config.get_main_option("sqlalchemy.url", "")


def run_migrations_offline() -> None:
    """Offline mode: emit SQL to stdout without connecting to the DB.
    Useful for generating SQL scripts to review before applying."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Tell Alembic about our custom types so it doesn't drop/recreate them
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online mode: connect to DB and run migrations directly."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # NullPool: no connection reuse — safe for migrations
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            # Compare server defaults so Alembic detects DEFAULT changes
            compare_server_defaults=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()