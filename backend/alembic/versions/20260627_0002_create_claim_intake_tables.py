"""create claim intake tables

Revision ID: 20260627_0002
Revises: 20260626_0001
Create Date: 2026-06-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260627_0002"
down_revision: Union[str, None] = "20260626_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "claim_intakes",
        sa.Column("claim_id", sa.String(length=64), nullable=False),
        sa.Column("member_id", sa.String(length=64), nullable=False),
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("claim_category", sa.String(length=64), nullable=False),
        sa.Column("treatment_date", sa.Date(), nullable=False),
        sa.Column("claimed_amount", sa.Float(), nullable=False),
        sa.Column("ytd_claims_amount", sa.Float(), nullable=True),
        sa.Column("hospital_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=64), nullable=True),
        sa.Column("approved_amount", sa.Float(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("validation_status", sa.String(length=64), nullable=False),
        sa.Column("member_action_code", sa.String(length=128), nullable=True),
        sa.Column("rejection_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trace", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("component_failures", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("claim_id"),
    )
    op.create_table(
        "uploaded_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("claim_id", sa.String(length=64), nullable=False),
        sa.Column("file_id", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("storage_uri", sa.String(length=512), nullable=True),
        sa.Column("declared_type", sa.String(length=64), nullable=True),
        sa.Column("classified_type", sa.String(length=64), nullable=False),
        sa.Column("classification_confidence", sa.Float(), nullable=False),
        sa.Column("classification_source", sa.String(length=64), nullable=False),
        sa.Column("quality", sa.String(length=64), nullable=False),
        sa.Column("patient_name_on_doc", sa.String(length=255), nullable=True),
        sa.Column("validation_status", sa.String(length=64), nullable=False),
        sa.Column("validation_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claim_intakes.claim_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_id", "file_id", name="uq_uploaded_documents_claim_file"),
    )


def downgrade() -> None:
    op.drop_table("uploaded_documents")
    op.drop_table("claim_intakes")
