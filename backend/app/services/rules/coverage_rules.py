"""Coverage rules: C01–C06 — exclusions, waiting periods, pre-authorization, annual limits."""
from __future__ import annotations

import json
import re

from app.models import ClaimSubmission
from app.models.policy import PolicyMember, PolicyTerms
from app.services.rules.financial_rules import line_items as _line_items


# ── Public rule functions ─────────────────────────────────────────────────────


def claim_text(submission: ClaimSubmission) -> str:
    return json.dumps([doc.content or {} for doc in submission.documents], sort_keys=True).lower()


def exclusion_reason(text: str, policy: PolicyTerms) -> str | None:
    for term in policy.exclusions.conditions:
        normalized = term.lower()
        if "obesity" in normalized and ("obesity" in text or "bariatric" in text or "diet" in text):
            return f"Treatment is excluded under policy exclusion: {term}."
        if normalized in text:
            return f"Treatment is excluded under policy exclusion: {term}."
    return None


def vision_exclusion_reason(submission: ClaimSubmission, text: str, policy: PolicyTerms) -> str | None:
    if submission.claim_category != "VISION":
        return None
    for term in policy.exclusions.vision_exclusions:
        if term.lower() in text:
            return f"Vision item is excluded under policy exclusion: {term}."
    config = policy.opd_categories["vision"]
    for item in config.excluded_items or []:
        if item.lower() in text:
            return f"Vision item is excluded under category rule: {item}."
    return None


def waiting_period_reason(
    submission: ClaimSubmission, member: PolicyMember, text: str, policy: PolicyTerms
) -> str | None:
    if member.join_date is None:
        return None
    for condition, days in policy.waiting_periods.specific_conditions.items():
        condition_text = condition.replace("_", " ")
        aliases = {condition_text}
        if condition == "diabetes":
            aliases.add("diabetes mellitus")
        if any(re.search(rf"\b{re.escape(alias)}\b", text) for alias in aliases):
            from datetime import date
            eligible_from = member.join_date.toordinal() + days
            eligible_date = date.fromordinal(eligible_from)
            if submission.treatment_date < eligible_date:
                return (
                    f"{condition_text.title()} treatment is in the {days}-day waiting period. "
                    f"Member is eligible for this condition from {eligible_date.isoformat()}."
                )
    return None


def pre_auth_reason(submission: ClaimSubmission, policy: PolicyTerms, claim_id: str) -> str | None:
    config = policy.opd_categories[submission.claim_category.lower()]
    high_value_tests = config.high_value_tests_requiring_pre_auth or []
    if not high_value_tests or config.pre_auth_threshold is None:
        return None
    for test in high_value_tests:
        test_text = test.lower()
        for item in _line_items(submission):
            description = str(item.get("description", item.get("test_name", ""))).lower()
            amount = float(item.get("amount", submission.claimed_amount))
            if test_text in description and amount > config.pre_auth_threshold:
                return _msg_pre_auth_missing(claim_id, test, amount, config.pre_auth_threshold)
    return None


def annual_limit_reason(submission: ClaimSubmission, policy: PolicyTerms) -> str | None:
    ytd_claims = submission.ytd_claims_amount or 0
    projected_total = ytd_claims + submission.claimed_amount
    if projected_total > policy.coverage.annual_opd_limit:
        return (
            f"Projected annual OPD claims would be INR {projected_total:.0f}, exceeding the annual "
            f"OPD limit of INR {policy.coverage.annual_opd_limit:.0f}."
        )
    return None


# ── Private helpers ───────────────────────────────────────────────────────────


def _msg_pre_auth_missing(claim_id: str, test_name: str, amount: float, threshold: float) -> str:
    return (
        f"Claim on hold \u2014 Pre-Authorization Approval required.\n\n"
        f"Your Diagnostic claim (Claim ID: {claim_id}) includes a procedure that requires\n"
        f"prior approval from the insurer before reimbursement can be processed.\n\n"
        f"Procedure detected: {test_name}\n"
        f"Claimed amount:     \u20b9{amount:,.0f}\n"
        f"Pre-auth required:  Yes (mandatory for {test_name} above \u20b9{threshold:,.0f})\n\n"
        f"If you already have pre-authorization:\n"
        f"  Upload your Pre-Authorization Approval Letter. The letter must be valid\n"
        f"  (within 30 days of the procedure date) and show an approval reference number.\n\n"
        f"If you do not have pre-authorization:\n"
        f"  Cashless/reimbursement for this procedure cannot be processed without prior\n"
        f"  approval. Contact Plum support immediately \u2014 approvals cannot be granted\n"
        f"  retroactively in most cases.\n\n"
        f"Policy Reference: Section 4 \u2014 Pre-Authorization Requirements"
    )
