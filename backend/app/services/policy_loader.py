import logging
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    CoverageLimitRecord,
    DocumentRequirementRecord,
    ExclusionRecord,
    FraudThresholdRecord,
    MemberRecord,
    NetworkHospitalRecord,
    OpdCategoryRecord,
    PolicyRecord,
    PreAuthorizationRuleRecord,
    WaitingPeriodRecord,
)
from app.db.session import SessionLocal
from app.models.policy import PolicyTerms

logger = logging.getLogger(__name__)

POLICY_TERMS_PATH = Path(__file__).resolve().parents[3] / "policy_terms.json"


class PolicyLoadError(RuntimeError):
    pass


def read_policy_terms(path: Path = POLICY_TERMS_PATH) -> PolicyTerms:
    try:
        return PolicyTerms.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyLoadError(f"Policy terms file was not found at {path}.") from exc
    except ValidationError as exc:
        raise PolicyLoadError(f"Policy terms validation failed: {exc}") from exc


def load_policy_terms(path: Path = POLICY_TERMS_PATH) -> PolicyTerms:
    policy = read_policy_terms(path)

    if SessionLocal is None:
        raise PolicyLoadError("DATABASE_URL is not configured; policy data cannot be loaded.")

    db = SessionLocal()
    try:
        upsert_policy_terms(db, policy)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise PolicyLoadError(f"Failed to load policy terms into Postgres: {exc}") from exc
    finally:
        db.close()

    return policy


def load_policy_terms_on_startup() -> PolicyTerms:
    policy = read_policy_terms()
    try:
        if SessionLocal is None:
            raise PolicyLoadError("DATABASE_URL is not configured; policy data cannot be loaded.")

        db = SessionLocal()
        try:
            upsert_policy_terms(db, policy)
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            raise PolicyLoadError(f"Failed to load policy terms into Postgres: {exc}") from exc
        finally:
            db.close()
    except PolicyLoadError:
        if settings.environment.lower() in {"local", "test"}:
            logger.warning(
                "Skipping policy DB load in %s environment; continuing with in-memory policy terms.",
                settings.environment,
                exc_info=True,
            )
            return policy
        raise
    return policy


def upsert_policy_terms(db: Session, policy: PolicyTerms) -> None:
    policy_id = policy.policy_id

    _delete_policy_children(db, policy_id)

    db.merge(
        PolicyRecord(
            policy_id=policy.policy_id,
            policy_name=policy.policy_name,
            insurer=policy.insurer,
            holder_company_name=policy.policy_holder.company_name,
            employee_count=policy.policy_holder.employee_count,
            policy_start_date=policy.policy_holder.policy_start_date,
            policy_end_date=policy.policy_holder.policy_end_date,
            renewal_status=policy.policy_holder.renewal_status,
            raw_policy=policy.as_json_dict(),
        )
    )
    db.flush()

    db.add(
        CoverageLimitRecord(
            policy_id=policy_id,
            sum_insured_per_employee=policy.coverage.sum_insured_per_employee,
            annual_opd_limit=policy.coverage.annual_opd_limit,
            per_claim_limit=policy.coverage.per_claim_limit,
            family_floater=policy.coverage.family_floater.model_dump(mode="json"),
        )
    )

    db.add_all(
        MemberRecord(
            policy_id=policy_id,
            member_id=member.member_id,
            name=member.name,
            date_of_birth=member.date_of_birth,
            gender=member.gender,
            relationship=member.relationship,
            join_date=member.join_date,
            dependents=member.dependents,
            primary_member_id=member.primary_member_id,
        )
        for member in policy.members
    )

    db.add_all(
        DocumentRequirementRecord(
            policy_id=policy_id,
            claim_category=str(category),
            required_documents=[str(document_type) for document_type in requirement.required],
            optional_documents=[str(document_type) for document_type in requirement.optional],
        )
        for category, requirement in policy.document_requirements.items()
    )

    db.add_all(
        OpdCategoryRecord(
            policy_id=policy_id,
            category=category.upper(),
            sub_limit=config.sub_limit,
            copay_percent=config.copay_percent,
            covered=config.covered,
            rules=config.model_dump(mode="json"),
        )
        for category, config in policy.opd_categories.items()
    )

    db.add_all(
        ExclusionRecord(policy_id=policy_id, exclusion_type="condition", term=term)
        for term in policy.exclusions.conditions
    )
    db.add_all(
        ExclusionRecord(policy_id=policy_id, exclusion_type="dental", term=term)
        for term in policy.exclusions.dental_exclusions
    )
    db.add_all(
        ExclusionRecord(policy_id=policy_id, exclusion_type="vision", term=term)
        for term in policy.exclusions.vision_exclusions
    )

    db.add_all(
        [
            WaitingPeriodRecord(
                policy_id=policy_id,
                waiting_period_type="initial",
                days=policy.waiting_periods.initial_waiting_period_days,
            ),
            WaitingPeriodRecord(
                policy_id=policy_id,
                waiting_period_type="pre_existing_conditions",
                days=policy.waiting_periods.pre_existing_conditions_days,
            ),
        ]
    )
    db.add_all(
        WaitingPeriodRecord(
            policy_id=policy_id,
            waiting_period_type=f"specific_condition:{condition}",
            days=days,
        )
        for condition, days in policy.waiting_periods.specific_conditions.items()
    )

    db.add(
        PreAuthorizationRuleRecord(
            policy_id=policy_id,
            required_for=policy.pre_authorization.required_for,
            validity_days=policy.pre_authorization.validity_days,
        )
    )

    db.add(
        FraudThresholdRecord(
            policy_id=policy_id,
            same_day_claims_limit=policy.fraud_thresholds.same_day_claims_limit,
            monthly_claims_limit=policy.fraud_thresholds.monthly_claims_limit,
            high_value_claim_threshold=policy.fraud_thresholds.high_value_claim_threshold,
            auto_manual_review_above=policy.fraud_thresholds.auto_manual_review_above,
            fraud_score_manual_review_threshold=(
                policy.fraud_thresholds.fraud_score_manual_review_threshold
            ),
        )
    )

    db.add_all(
        NetworkHospitalRecord(policy_id=policy_id, hospital_name=hospital)
        for hospital in policy.network_hospitals
    )


def _delete_policy_children(db: Session, policy_id: str) -> None:
    for table in (
        CoverageLimitRecord,
        DocumentRequirementRecord,
        OpdCategoryRecord,
        ExclusionRecord,
        WaitingPeriodRecord,
        PreAuthorizationRuleRecord,
        FraudThresholdRecord,
        NetworkHospitalRecord,
        MemberRecord,
    ):
        db.execute(delete(table).where(table.policy_id == policy_id))
