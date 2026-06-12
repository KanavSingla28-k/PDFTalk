"""add revoked_at

Revision ID: 0003_add_revoked_at
Revises: ef85fde67e77
Create Date: 2026-06-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0003_add_revoked_at'
down_revision = 'ef85fde67e77'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('refresh_tokens', sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True))

def downgrade() -> None:
    op.drop_column('refresh_tokens', 'revoked_at')
