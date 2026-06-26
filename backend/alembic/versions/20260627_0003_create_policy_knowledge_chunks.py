"""create policy knowledge chunks

Revision ID: 20260627_0003
Revises: 20260627_0002
Create Date: 2026-06-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision: str = "20260627_0003"
down_revision: Union[str, None] = "20260627_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "policy_knowledge_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_id", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=False),
        sa.Column("rule_category", sa.String(length=128), nullable=False),
        sa.Column("claim_category", sa.String(length=64), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("embedding", Vector(64), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["policies.policy_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "evidence_id", name="uq_policy_knowledge_policy_evidence"),
    )
    op.execute(
        """
        CREATE INDEX ix_policy_knowledge_chunks_embedding_hnsw
        ON policy_knowledge_chunks
        USING hnsw (embedding vector_cosine_ops)
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'halfvec') THEN
                CREATE INDEX ix_policy_knowledge_chunks_embedding_halfvec_hnsw
                ON policy_knowledge_chunks
                USING hnsw ((embedding::halfvec(64)) halfvec_cosine_ops);
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE INDEX ix_policy_knowledge_chunks_text_fts
        ON policy_knowledge_chunks
        USING gin (to_tsvector('english', text))
        """
    )
    op.create_index(
        "ix_policy_knowledge_chunks_policy_category",
        "policy_knowledge_chunks",
        ["policy_id", "claim_category", "rule_category"],
    )


def downgrade() -> None:
    op.drop_index("ix_policy_knowledge_chunks_policy_category", table_name="policy_knowledge_chunks")
    op.execute("DROP INDEX IF EXISTS ix_policy_knowledge_chunks_text_fts")
    op.execute("DROP INDEX IF EXISTS ix_policy_knowledge_chunks_embedding_halfvec_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_policy_knowledge_chunks_embedding_hnsw")
    op.drop_table("policy_knowledge_chunks")
