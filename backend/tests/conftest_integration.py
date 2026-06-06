# tests/conftest_integration.py
import os
import uuid
import pytest
import boto3
from moto import mock_aws
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from typing import cast

# ---------------------------------------------------------------------------
# Real PostgreSQL engine — points at your dev Docker container
# ---------------------------------------------------------------------------
PG_URL = os.getenv(
    "INTEGRATION_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5433/pdftalk",
)

# We use the sync psycopg driver here because:
#   - run_ingest() uses SessionLocal (sync)
#   - Alembic runs sync
# asyncpg is only needed by the FastAPI async path.


@pytest.fixture(scope="session")
def pg_engine():
    """
    Session-scoped sync engine against the real pgvector Postgres.
    Requires pdftalk-postgres Docker container to be running.
    """
    engine = create_engine(PG_URL, echo=False)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def run_migrations(pg_engine):
    """
    Run alembic upgrade head once per test session against the real DB.
    Idempotent — safe to run on an already-migrated DB.
    """
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option(
        "sqlalchemy.url",
        PG_URL.replace("+psycopg", ""),  # alembic wants plain postgresql://
    )
    command.upgrade(alembic_cfg, "head")
    yield
    # Don't downgrade — leave the schema in place between runs for speed


@pytest.fixture()
def pg_session(pg_engine, run_migrations):
    connection = pg_engine.connect()
    transaction = connection.begin()

    Session = sessionmaker(bind=connection)
    session = Session()

    import app.db.sync_session as sync_session_module
    import app.workers.ingest as ingest_module

    original_sync_sessionlocal = sync_session_module.SessionLocal
    original_ingest_sessionlocal = ingest_module.SessionLocal

    class _NonClosingSession:
        def __init__(self, s):
            self._s = s

        def __getattr__(self, name):
            return getattr(self._s, name)

        def __enter__(self):
            return self._s

        def __exit__(self, *args):
            # Prevent worker from closing the test session
            pass

    class _PatchedFactory:
        def __call__(self):
            return _NonClosingSession(session)

    patched_factory = _PatchedFactory()

    # Patch BOTH references
    sync_session_module.SessionLocal = cast(
        type(original_sync_sessionlocal),
        patched_factory,
    )

    ingest_module.SessionLocal = cast(
        type(original_ingest_sessionlocal),
        patched_factory,
    )

    yield session

    # Restore originals
    sync_session_module.SessionLocal = original_sync_sessionlocal
    ingest_module.SessionLocal = original_ingest_sessionlocal

    session.close()
    transaction.rollback()
    connection.close()