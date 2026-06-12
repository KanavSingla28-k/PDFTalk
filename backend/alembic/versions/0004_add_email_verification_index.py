"""add email verification index

Revision ID: 0004_add_email_verification_index
Revises: 0003_add_revoked_at
Create Date: 2026-06-13 00:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0004_add_email_verification_index'
down_revision = '0003_add_revoked_at'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # unique=True already creates a b-tree index implicitly in postgres,
    # but we create this explicit index if it doesn't already exist to be safe/consistent.
    op.create_index('idx_email_verifications_token_hash', 'email_verifications', ['token_hash'], unique=False)

def downgrade() -> None:
    op.drop_index('idx_email_verifications_token_hash', table_name='email_verifications')
