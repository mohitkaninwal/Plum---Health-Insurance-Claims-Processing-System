"""Update policy_knowledge_chunks embedding from 64-dim to 384-dim (all-MiniLM-L6-v2).

Revision ID: 20260628_0004
Revises: 20260627_0003
Create Date: 2026-06-28

Note: Changing vector dimensions requires dropping and re-adding the column.
      Re-index the knowledge base after applying this migration by calling
      `index_policy_knowledge_on_startup` or restarting the service.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260628_0004"
down_revision = "20260627_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE policy_knowledge_chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE policy_knowledge_chunks ADD COLUMN embedding vector(384)")


def downgrade() -> None:
    op.execute("ALTER TABLE policy_knowledge_chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE policy_knowledge_chunks ADD COLUMN embedding vector(64)")
