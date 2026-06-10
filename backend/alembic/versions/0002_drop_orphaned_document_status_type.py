"""drop_orphaned_document_status_type

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-06

The documents.status column was always created as Text in migration 0001.
Migration 0001 also ran:

    CREATE TYPE document_status AS ENUM ('PENDING', 'PROCESSING', 'READY', 'FAILED')

...but that type was never applied to any column — it is an orphan.
This migration removes it to keep the schema clean and avoid confusion.

No table or column changes. Safe to run on a live DB.
"""

from alembic import op


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the orphaned Postgres enum type created in 0001.
    # IF EXISTS: safe to run even if a previous partial apply already dropped it.
    op.execute("DROP TYPE IF EXISTS document_status")


def downgrade() -> None:
    # Recreate the type so 0001 is a consistent base if someone downgrades.
    # The type is not used by any column — recreating it is purely for
    # migration chain consistency.
    op.execute(
        "CREATE TYPE document_status AS ENUM ('PENDING', 'PROCESSING', 'READY', 'FAILED')"
    )
