"""create policy tables

Revision ID: 20260626_0001
Revises:
Create Date: 2026-06-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260626_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "policies",
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("policy_name", sa.String(length=255), nullable=False),
        sa.Column("insurer", sa.String(length=255), nullable=False),
        sa.Column("holder_company_name", sa.String(length=255), nullable=False),
        sa.Column("employee_count", sa.Integer(), nullable=False),
        sa.Column("policy_start_date", sa.Date(), nullable=False),
        sa.Column("policy_end_date", sa.Date(), nullable=False),
        sa.Column("renewal_status", sa.String(length=64), nullable=False),
        sa.Column("raw_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("policy_id"),
    )
    op.create_table(
        "coverage_limits",
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("sum_insured_per_employee", sa.Float(), nullable=False),
        sa.Column("annual_opd_limit", sa.Float(), nullable=False),
        sa.Column("per_claim_limit", sa.Float(), nullable=False),
        sa.Column("family_floater", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["policies.policy_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("policy_id"),
    )
    op.create_table(
        "document_requirements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("claim_category", sa.String(length=64), nullable=False),
        sa.Column("required_documents", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("optional_documents", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["policies.policy_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "policy_id",
            "claim_category",
            name="uq_document_requirements_policy_category",
        ),
    )
    op.create_table(
        "exclusions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("exclusion_type", sa.String(length=64), nullable=False),
        sa.Column("term", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["policies.policy_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "fraud_thresholds",
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("same_day_claims_limit", sa.Integer(), nullable=False),
        sa.Column("monthly_claims_limit", sa.Integer(), nullable=False),
        sa.Column("high_value_claim_threshold", sa.Float(), nullable=False),
        sa.Column("auto_manual_review_above", sa.Float(), nullable=False),
        sa.Column("fraud_score_manual_review_threshold", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["policies.policy_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("policy_id"),
    )
    op.create_table(
        "members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("member_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("gender", sa.String(length=16), nullable=False),
        sa.Column("relationship", sa.String(length=64), nullable=False),
        sa.Column("join_date", sa.Date(), nullable=True),
        sa.Column("dependents", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("primary_member_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["policy_id"], ["policies.policy_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "member_id", name="uq_members_policy_member"),
    )
    op.create_table(
        "network_hospitals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("hospital_name", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["policies.policy_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "hospital_name", name="uq_network_hospitals_policy_name"),
    )
    op.create_table(
        "opd_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("sub_limit", sa.Float(), nullable=False),
        sa.Column("copay_percent", sa.Float(), nullable=False),
        sa.Column("covered", sa.Boolean(), nullable=False),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["policies.policy_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "category", name="uq_opd_categories_policy_category"),
    )
    op.create_table(
        "pre_authorization_rules",
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("required_for", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("validity_days", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["policies.policy_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("policy_id"),
    )
    op.create_table(
        "waiting_periods",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("waiting_period_type", sa.String(length=128), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["policies.policy_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "policy_id",
            "waiting_period_type",
            name="uq_waiting_periods_policy_type",
        ),
    )


def downgrade() -> None:
    op.drop_table("waiting_periods")
    op.drop_table("pre_authorization_rules")
    op.drop_table("opd_categories")
    op.drop_table("network_hospitals")
    op.drop_table("members")
    op.drop_table("fraud_thresholds")
    op.drop_table("exclusions")
    op.drop_table("document_requirements")
    op.drop_table("coverage_limits")
    op.drop_table("policies")
