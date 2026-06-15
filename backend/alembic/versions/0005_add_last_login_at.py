"""add last_login_at to user

Revision ID: 0005_add_last_login_at
Revises: 0004_add_email_verif_index
Create Date: 2026-06-16 02:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0005_add_last_login_at'
down_revision = '0004_add_email_verif_index'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))

def downgrade() -> None:
    op.drop_column('users', 'last_login_at')
