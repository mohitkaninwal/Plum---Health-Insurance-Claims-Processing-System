from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship as orm_relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PolicyRecord(Base):
    __tablename__ = "policies"

    policy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    policy_name: Mapped[str] = mapped_column(String(255), nullable=False)
    insurer: Mapped[str] = mapped_column(String(255), nullable=False)
    holder_company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    employee_count: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    policy_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    renewal_status: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    members: Mapped[list["MemberRecord"]] = orm_relationship(
        back_populates="policy",
        cascade="all, delete-orphan",
    )


class MemberRecord(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.policy_id", ondelete="CASCADE"))
    member_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[str] = mapped_column(String(16), nullable=False)
    relationship: Mapped[str] = mapped_column(String(64), nullable=False)
    join_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    dependents: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    primary_member_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    policy: Mapped[PolicyRecord] = orm_relationship(back_populates="members")

    __table_args__ = (UniqueConstraint("policy_id", "member_id", name="uq_members_policy_member"),)


class CoverageLimitRecord(Base):
    __tablename__ = "coverage_limits"

    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.policy_id", ondelete="CASCADE"), primary_key=True)
    sum_insured_per_employee: Mapped[float] = mapped_column(Float, nullable=False)
    annual_opd_limit: Mapped[float] = mapped_column(Float, nullable=False)
    per_claim_limit: Mapped[float] = mapped_column(Float, nullable=False)
    family_floater: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class DocumentRequirementRecord(Base):
    __tablename__ = "document_requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.policy_id", ondelete="CASCADE"))
    claim_category: Mapped[str] = mapped_column(String(64), nullable=False)
    required_documents: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    optional_documents: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint("policy_id", "claim_category", name="uq_document_requirements_policy_category"),
    )


class OpdCategoryRecord(Base):
    __tablename__ = "opd_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.policy_id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    sub_limit: Mapped[float] = mapped_column(Float, nullable=False)
    copay_percent: Mapped[float] = mapped_column(Float, nullable=False)
    covered: Mapped[bool] = mapped_column(nullable=False)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (UniqueConstraint("policy_id", "category", name="uq_opd_categories_policy_category"),)


class ExclusionRecord(Base):
    __tablename__ = "exclusions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.policy_id", ondelete="CASCADE"))
    exclusion_type: Mapped[str] = mapped_column(String(64), nullable=False)
    term: Mapped[str] = mapped_column(Text, nullable=False)


class WaitingPeriodRecord(Base):
    __tablename__ = "waiting_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.policy_id", ondelete="CASCADE"))
    waiting_period_type: Mapped[str] = mapped_column(String(128), nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("policy_id", "waiting_period_type", name="uq_waiting_periods_policy_type"),
    )


class PreAuthorizationRuleRecord(Base):
    __tablename__ = "pre_authorization_rules"

    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.policy_id", ondelete="CASCADE"), primary_key=True)
    required_for: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    validity_days: Mapped[int] = mapped_column(Integer, nullable=False)


class FraudThresholdRecord(Base):
    __tablename__ = "fraud_thresholds"

    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.policy_id", ondelete="CASCADE"), primary_key=True)
    same_day_claims_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_claims_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    high_value_claim_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    auto_manual_review_above: Mapped[float] = mapped_column(Float, nullable=False)
    fraud_score_manual_review_threshold: Mapped[float] = mapped_column(Float, nullable=False)


class NetworkHospitalRecord(Base):
    __tablename__ = "network_hospitals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.policy_id", ondelete="CASCADE"))
    hospital_name: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        UniqueConstraint("policy_id", "hospital_name", name="uq_network_hospitals_policy_name"),
    )


class ClaimIntakeRecord(Base):
    __tablename__ = "claim_intakes"

    claim_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    member_id: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_category: Mapped[str] = mapped_column(String(64), nullable=False)
    treatment_date: Mapped[date] = mapped_column(Date, nullable=False)
    claimed_amount: Mapped[float] = mapped_column(Float, nullable=False)
    ytd_claims_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    hospital_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(64), nullable=False)
    member_action_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rejection_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    trace: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    component_failures: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    documents: Mapped[list["UploadedDocumentRecord"]] = orm_relationship(
        back_populates="claim",
        cascade="all, delete-orphan",
    )


class UploadedDocumentRecord(Base):
    __tablename__ = "uploaded_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("claim_intakes.claim_id", ondelete="CASCADE"),
        nullable=False,
    )
    file_id: Mapped[str] = mapped_column(String(64), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    declared_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classified_type: Mapped[str] = mapped_column(String(64), nullable=False)
    classification_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    classification_source: Mapped[str] = mapped_column(String(64), nullable=False)
    quality: Mapped[str] = mapped_column(String(64), nullable=False)
    patient_name_on_doc: Mapped[str | None] = mapped_column(String(255), nullable=True)
    validation_status: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    claim: Mapped[ClaimIntakeRecord] = orm_relationship(back_populates="documents")

    __table_args__ = (UniqueConstraint("claim_id", "file_id", name="uq_uploaded_documents_claim_file"),)
