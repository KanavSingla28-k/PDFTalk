"""batch_3_schema_updates

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-23 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Update documents.status default
    op.alter_column("documents", "status", existing_type=sa.Text(), server_default="PENDING_UPLOAD")

    # 2. Add CHECK constraint for document status
    op.create_check_constraint(
        "check_valid_document_status",
        "documents",
        "status IN ('PENDING_UPLOAD', 'PENDING', 'PROCESSING', 'READY', 'FAILED')",
    )

    # 3. Add HNSW index to chunks.embedding
    op.create_index(
        "idx_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # 4. Create trigger function for updated_at
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    # Apply trigger to users, documents, and chats
    tables = ["users", "documents", "chats"]
    for table in tables:
        op.execute(f"""
            CREATE TRIGGER update_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """)


def downgrade() -> None:
    # Remove triggers
    tables = ["users", "documents", "chats"]
    for table in tables:
        op.execute(f"DROP TRIGGER IF EXISTS update_{table}_updated_at ON {table};")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column();")

    # Drop HNSW index
    op.drop_index(
        "idx_chunks_embedding_hnsw",
        table_name="chunks",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # Drop CHECK constraint
    op.drop_constraint("check_valid_document_status", "documents", type_="check")

    # Revert default for documents.status
    op.alter_column("documents", "status", existing_type=sa.Text(), server_default="PENDING")
