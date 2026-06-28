"""Fraud rules: FR1–FR4 — same-day claims, high-value thresholds, compliance signals."""
from __future__ import annotations

from app.models import ClaimSubmission
from app.models.policy import PolicyTerms


def fraud_reason(submission: ClaimSubmission, policy: PolicyTerms) -> str | None:
    same_day_count = sum(
        1 for claim in submission.claims_history if claim.date == submission.treatment_date
    )
    if same_day_count >= policy.fraud_thresholds.same_day_claims_limit:
        return (
            f"{same_day_count + 1} same-day claims for member {submission.member_id}; "
            "manual review required before payment."
        )
    if submission.claimed_amount > policy.fraud_thresholds.auto_manual_review_above:
        return "High-value claim exceeds automatic approval threshold; manual review required."
    return None
