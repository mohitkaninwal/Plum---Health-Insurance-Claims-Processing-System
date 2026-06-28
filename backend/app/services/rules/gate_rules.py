"""Gate rules: R01–R06 — policy/member validity and submission compliance."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from app.models import ClaimSubmission, ExtractedDocumentData
from app.models.policy import PolicyMember, PolicyTerms

_CATEGORY_LABELS: dict[str, str] = {
    "CONSULTATION": "Consultation",
    "DIAGNOSTIC": "Diagnostic",
    "PHARMACY": "Pharmacy",
    "DENTAL": "Dental",
    "VISION": "Vision",
    "ALTERNATIVE_MEDICINE": "Alternative Medicine",
}


# ── Public rule functions ─────────────────────────────────────────────────────


def find_member(member_id: str, policy: PolicyTerms) -> PolicyMember | None:
    return next((m for m in policy.members if m.member_id == member_id), None)


def member_name(submission: ClaimSubmission, policy: PolicyTerms) -> str:
    for m in policy.members:
        if m.member_id == submission.member_id:
            return m.name
    return submission.member_id


def member_dependents(submission: ClaimSubmission, policy: PolicyTerms) -> list[str]:
    member = find_member(submission.member_id, policy)
    if member is None:
        return []
    members_by_id = {m.member_id: m for m in policy.members}
    result: list[str] = []
    for dep_id in member.dependents:
        dep = members_by_id.get(dep_id)
        if dep is not None:
            result.append(dep.name)
    for m in policy.members:
        if m.primary_member_id == member.member_id:
            result.append(m.name)
    return result


def policy_validity_reason(submission: ClaimSubmission, policy: PolicyTerms) -> str | None:
    holder = policy.policy_holder
    if holder.renewal_status.upper() != "ACTIVE":
        return f"Policy {policy.policy_id} is not active; renewal status is {holder.renewal_status}."
    if submission.treatment_date < holder.policy_start_date:
        return (
            f"Treatment date {submission.treatment_date.isoformat()} is before policy start date "
            f"{holder.policy_start_date.isoformat()}."
        )
    if submission.treatment_date > holder.policy_end_date:
        return (
            f"Treatment date {submission.treatment_date.isoformat()} is after policy end date "
            f"{holder.policy_end_date.isoformat()}."
        )
    return None


def submission_rules_reason(submission: ClaimSubmission, policy: PolicyTerms, claim_id: str) -> str | None:
    if submission.claimed_amount < policy.submission_rules.minimum_claim_amount:
        return (
            f"Claimed amount {policy.submission_rules.currency} {submission.claimed_amount:.0f} is below "
            f"the minimum claim amount of {policy.submission_rules.currency} "
            f"{policy.submission_rules.minimum_claim_amount:.0f}."
        )

    submitted_on = _submitted_on(submission)
    days_after_treatment = (submitted_on - submission.treatment_date).days
    deadline_days = policy.submission_rules.deadline_days_from_treatment
    if days_after_treatment > deadline_days:
        category_label = _readable_category(submission.claim_category)
        days_overdue = days_after_treatment - deadline_days
        return _msg_deadline_exceeded(
            claim_id,
            category_label,
            submission.treatment_date,
            submitted_on,
            deadline_days,
            days_overdue,
            days_after_treatment,
        )
    return None


def category_coverage_reason(submission: ClaimSubmission, policy: PolicyTerms) -> str | None:
    config = policy.opd_categories[submission.claim_category.lower()]
    if not config.covered:
        return f"{submission.claim_category} claims are not covered under policy {policy.policy_id}."
    return None


def patient_name_matches_member_family_reason(
    submission: ClaimSubmission,
    member: PolicyMember | None,
    policy: PolicyTerms,
    extracted_documents: list[ExtractedDocumentData],
    claim_id: str,
) -> str | None:
    observed_names = _observed_patient_names(submission, extracted_documents)
    if not observed_names or member is None:
        return None

    allowed_names = _allowed_patient_names(member, policy)
    if not allowed_names:
        return None

    unrecognized = [name for name in observed_names if _name_key(name) not in allowed_names]
    if not unrecognized:
        return None

    category_label = _readable_category(submission.claim_category)
    dependents = member_dependents(submission, policy)
    return _msg_patient_mismatch(
        claim_id,
        category_label,
        unrecognized,
        member.name,
        submission.member_id,
        dependents,
    )


# ── Private helpers ───────────────────────────────────────────────────────────


def _submitted_on(submission: ClaimSubmission) -> date:
    for doc in submission.documents:
        content = doc.content or {}
        raw_date = content.get("submitted_on") or content.get("submission_date")
        if isinstance(raw_date, date):
            return raw_date
        if isinstance(raw_date, str):
            try:
                return date.fromisoformat(raw_date)
            except ValueError:
                continue
    return submission.treatment_date


def _allowed_patient_names(member: PolicyMember, policy: PolicyTerms) -> dict[str, str]:
    allowed: dict[str, str] = {_name_key(member.name): member.name}
    members_by_id = {item.member_id: item for item in policy.members}

    for dependent_id in member.dependents:
        dependent = members_by_id.get(dependent_id)
        if dependent is not None:
            allowed[_name_key(dependent.name)] = dependent.name

    for item in policy.members:
        if item.primary_member_id == member.member_id:
            allowed[_name_key(item.name)] = item.name

    return allowed


def _observed_patient_names(
    submission: ClaimSubmission,
    extracted_documents: list[ExtractedDocumentData],
) -> list[str]:
    names: list[str] = []
    for document in submission.documents:
        if document.patient_name_on_doc:
            names.append(document.patient_name_on_doc)

    for item in extracted_documents:
        raw_name = item.fields.get("patient_name")
        if isinstance(raw_name, str) and raw_name.strip():
            names.append(raw_name.strip())
    return _dedupe_preserve_order(names)


def _name_key(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = _name_key(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _readable_category(category: Any) -> str:
    return _CATEGORY_LABELS.get(str(category).upper(), str(category).replace("_", " ").title())


def _msg_deadline_exceeded(
    claim_id: str,
    claim_category: str,
    treatment_date: date,
    submitted_on: date,
    deadline_days: int,
    days_overdue: int,
    days_after_treatment: int = 0,
) -> str:
    deadline_date = treatment_date + timedelta(days=deadline_days)
    return (
        f"Claim cannot be processed \u2014 Submission deadline passed.\n\n"
        f"Your {claim_category} claim (Claim ID: {claim_id}) was submitted outside the allowed window.\n\n"
        f"Treatment date:    {treatment_date.isoformat()}\n"
        f"Submission date:   {submitted_on.isoformat()} ({days_after_treatment} days after treatment)\n"
        f"Allowed window:    {deadline_days} days from treatment date\n"
        f"Deadline was:      {deadline_date.isoformat()}\n"
        f"Overdue by:        {days_overdue} days\n\n"
        f"Per your policy, claims must be submitted within {deadline_days} days of the\n"
        f"treatment date. This claim is not eligible for reimbursement under the standard process.\n\n"
        f"If you have a valid reason for the delay (hospitalisation, travel, natural disaster),\n"
        f"you may raise a waiver request with supporting evidence through Plum support.\n"
        f"Waivers are subject to insurer approval and are not guaranteed."
    )


def _msg_patient_mismatch(
    claim_id: str,
    claim_category: str,
    names_found: list[str],
    policy_member_name: str,
    member_id: str,
    dependents: list[str],
) -> str:
    names_joined = ", ".join(names_found)
    dependent_list = ", ".join(dependents) if dependents else "none listed"
    return (
        f"Claim on hold \u2014 Patient name on document does not match policy records.\n\n"
        f"  Name(s) on documents:  {names_joined}\n"
        f"  Name on policy:        {policy_member_name}  (Member ID: {member_id})\n\n"
        f"This could be due to:\n"
        f'  \u2022 A spelling variation (e.g. "Rajesh" vs "Raj")\n'
        f"  \u2022 A nickname or informal name used at the clinic\n"
        f"  \u2022 A document belonging to a different person\n\n"
        f"What to do:\n"
        f"  If this is the same person \u2014 upload a government-issued ID (Aadhaar, PAN, or\n"
        f"  Passport) showing the name as it appears on your policy. Plum will manually\n"
        f"  verify and proceed.\n\n"
        f"  If this document belongs to a dependent \u2014 ensure the dependent is listed under\n"
        f"  your policy. Covered dependents for your account: {dependent_list}\n\n"
        f"  If this is an error \u2014 contact Plum support to correct your policy name before\n"
        f"  resubmitting."
    )
