"""pending_upload_status_assessment

Revision ID: 0006
Revises: ef85fde67e77
Create Date: 2026-06-17

Context
-------
The presigned URL upload flow (Step 2 of the performance improvement plan)
introduces a new DocumentStatus value: PENDING_UPLOAD.

This migration documents the deliberate assessment that **no schema change is
required** to support this new status. Here is why:

1. The `documents.status` column is defined as `sa.Text` (migration 0001, line 72):

       sa.Column("status", sa.Text, nullable=False, server_default="PENDING")

   It is NOT a Postgres ENUM type. The orphaned `CREATE TYPE document_status AS ENUM`
   that appeared in migration 0001 was never applied to any column, and was removed
   by migration 0002.

2. Because the column is plain TEXT, Postgres will accept 'PENDING_UPLOAD' as a
   value without any ALTER TABLE or ALTER TYPE statement.

3. The `server_default="PENDING"` on the column only fires for raw SQL inserts
   that omit the status column. All application code goes through the ORM with an
   explicit status, so the server_default is never triggered for PENDING_UPLOAD rows.

4. No CHECK constraint exists on the status column that would need updating.
   (Verified by inspecting migration 0001 — no CheckConstraint was added.)

Action taken
------------
- Python: DocumentStatus enum updated with PENDING_UPLOAD (models/document.py).
- Python: _ALLOWED_TRANSITIONS updated to include PENDING_UPLOAD → PENDING | FAILED.
- No SQL: zero schema changes required.

This migration is intentionally a no-op. It exists solely as an audit record.
"""

from alembic import op  # noqa: F401 — imported for Alembic chain consistency


# revision identifiers
revision = "0006"
down_revision = "0005_add_last_login_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    No schema changes required.

    The documents.status column is TEXT — it accepts 'PENDING_UPLOAD' without
    any ALTER TABLE statement. See module docstring for full rationale.
    """
    pass  # intentional no-op — see docstring above


def downgrade() -> None:
    """
    No schema changes were made in upgrade(), so nothing to reverse.

    If PENDING_UPLOAD rows exist in the database when downgrading past this
    migration (i.e. rolling back the Python code as well), those rows will
    have status='PENDING_UPLOAD' which the old Python enum does not recognise.
    Clean them up manually before downgrading the application code:

        UPDATE documents SET status='FAILED', error_message='Rolled back to pre-PENDING_UPLOAD schema'
        WHERE status = 'PENDING_UPLOAD';
    """
    pass  # intentional no-op
