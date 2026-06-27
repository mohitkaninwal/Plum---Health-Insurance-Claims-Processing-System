from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"

from app.models import (
    ClaimDecision,
    ClaimDecisionType,
    ClaimResponse,
    ClaimStatus,
    ClaimSubmission,
    ComponentFailure,
    DocumentQuality,
    DocumentType,
    EvalCaseResult,
    EvalMetrics,
    EvalRun,
    ExtractedDocumentData,
    LineItemDecision,
    LineItemDecisionType,
    MemberActionRequired,
    PolicyEvidence,
    TraceEvent,
    TraceLevel,
)
from app.models.policy import PolicyMember, PolicyTerms
from app.services.document_intake import classify_document
from app.services.extraction_pipeline import run_extraction_pipeline
from app.services.policy_loader import read_policy_terms
from app.services.policy_retriever import retrieve_policy_evidence

TEST_CASES_PATH = Path(__file__).resolve().parents[3] / "test_cases.json"


def process_claim(submission: ClaimSubmission, policy: PolicyTerms | None = None) -> ClaimResponse:
    policy = policy or read_policy_terms()
    if submission.policy_id != policy.policy_id:
        trace = [
            TraceEvent(
                component="ClaimIntakeAPI",
                level=TraceLevel.WARNING,
                message=(
                    f"Claim policy_id {submission.policy_id} does not match loaded policy "
                    f"{policy.policy_id}."
                ),
                input_summary={
                    "submission_policy_id": submission.policy_id,
                    "loaded_policy_id": policy.policy_id,
                },
                checks_performed=["policy_id_matches_active_policy"],
                confidence_impact=-0.01,
            )
        ]
        return _rejected(
            submission,
            trace,
            _policy_evidence(submission, policy),
            ["POLICY_MISMATCH"],
            f"Claim references policy {submission.policy_id}, but the active policy is {policy.policy_id}.",
            confidence=_confidence_score(submission, [], [], rule_certainty_impact=-0.01),
        )

    trace: list[TraceEvent] = [
        TraceEvent(
            component="ClaimIntakeAPI",
            message="Claim submission accepted.",
            input_summary={
                "member_id": submission.member_id,
                "policy_id": submission.policy_id,
                "claim_category": submission.claim_category,
                "claimed_amount": submission.claimed_amount,
                "document_count": len(submission.documents),
            },
            checks_performed=["required_submission_fields_present"],
        )
    ]
    evidence = _policy_evidence(submission, policy)
    claim_id = f"CLM_{uuid4().hex[:12].upper()}"

    early_response = _validate_documents(submission, policy, trace, evidence)
    if early_response is not None:
        return early_response

    extraction_result = run_extraction_pipeline(submission)
    submission = extraction_result.submission
    trace.extend(extraction_result.trace)
    if extraction_result.member_action_required is not None:
        message = extraction_result.member_action_required.message
        trace.append(
            TraceEvent(
                component="ConfidenceScorer",
                level=TraceLevel.WARNING,
                message="Confidence not finalized because the claim requires member action before adjudication.",
                input_summary=_confidence_inputs(
                    submission,
                    evidence,
                    extraction_result.extracted_documents,
                    extraction_result.component_failures,
                ),
                output_summary={"status": ClaimStatus.ACTION_REQUIRED},
                checks_performed=[
                    "document_quality",
                    "extraction_completeness",
                    "patient_consistency",
                    "policy_evidence_strength",
                    "component_failures",
                ],
                confidence_impact=extraction_result.confidence_impact,
            )
        )
        return ClaimResponse(
            status=ClaimStatus.ACTION_REQUIRED,
            submission=submission,
            reason=message,
            member_action_required=extraction_result.member_action_required,
            trace=trace,
            retrieved_policy_evidence=evidence,
            component_failures=extraction_result.component_failures,
            extracted_document_data=extraction_result.extracted_documents,
        )

    member = _member_for(submission.member_id, policy)
    component_failures: list[ComponentFailure] = list(extraction_result.component_failures)
    patient_name_reason = _patient_name_matches_member_family_reason(
        submission,
        member,
        policy,
        extraction_result.extracted_documents,
        claim_id,
    )
    if patient_name_reason:
        return _action_required_response(
            submission,
            trace,
            evidence,
            patient_name_reason,
            code="PATIENT_MISMATCH",
            claim_id=claim_id,
            component_failures=component_failures,
            extracted_document_data=extraction_result.extracted_documents,
        )
    confidence = _confidence_score(
        submission,
        evidence,
        extraction_result.extracted_documents,
        component_failures,
    )
    if member is None:
        return _rejected(
            submission,
            trace,
            evidence,
            ["MEMBER_NOT_FOUND"],
            f"Member {submission.member_id} is not listed under policy {policy.policy_id}.",
            confidence=_confidence_score(
                submission,
                evidence,
                extraction_result.extracted_documents,
                component_failures,
                rule_certainty_impact=-0.02,
            ),
            component_failures=component_failures,
            extracted_document_data=extraction_result.extracted_documents,
        )

    policy_validity_reason = _policy_validity_reason(submission, policy)
    if policy_validity_reason:
        return _rejected(
            submission,
            trace,
            evidence,
            ["POLICY_NOT_ACTIVE"],
            policy_validity_reason,
            confidence=_confidence_score(
                submission,
                evidence,
                extraction_result.extracted_documents,
                component_failures,
                rule_certainty_impact=-0.02,
            ),
            component_failures=component_failures,
            extracted_document_data=extraction_result.extracted_documents,
        )

    submission_rules_reason = _submission_rules_reason(submission, policy, claim_id)
    if submission_rules_reason:
        return _rejected(
            submission,
            trace,
            evidence,
            ["SUBMISSION_RULE_FAILED"],
            submission_rules_reason,
            confidence=_confidence_score(
                submission,
                evidence,
                extraction_result.extracted_documents,
                component_failures,
                rule_certainty_impact=-0.03,
            ),
            component_failures=component_failures,
            extracted_document_data=extraction_result.extracted_documents,
            claim_id=claim_id,
        )

    category_reason = _category_coverage_reason(submission, policy)
    if category_reason:
        return _rejected(
            submission,
            trace,
            evidence,
            ["CATEGORY_NOT_COVERED"],
            category_reason,
            confidence=_confidence_score(
                submission,
                evidence,
                extraction_result.extracted_documents,
                component_failures,
                rule_certainty_impact=-0.03,
            ),
            component_failures=component_failures,
            extracted_document_data=extraction_result.extracted_documents,
        )

    if submission.simulate_component_failure:
        component_failures.append(
            ComponentFailure(
                component="PolicyEvidenceRetriever",
                message="Hybrid retrieval timed out; deterministic policy checks continued.",
            )
        )
        confidence = _confidence_score(
            submission,
            evidence,
            extraction_result.extracted_documents,
            component_failures,
            rule_certainty_impact=-0.04,
        )
        trace.append(
            TraceEvent(
                component="PolicyEvidenceRetriever",
                level=TraceLevel.WARNING,
                message="Recoverable component failure recorded; adjudication continued.",
                checks_performed=["hybrid_policy_retrieval"],
                confidence_impact=-0.12,
                warnings=["Hybrid retrieval timed out; deterministic policy checks continued."],
            )
        )

    text = _claim_text(submission)

    exclusion_reason = _exclusion_reason(text, policy)
    if exclusion_reason:
        return _rejected(
            submission,
            trace,
            evidence,
            ["EXCLUDED_CONDITION"],
            exclusion_reason,
            confidence=_confidence_score(
                submission,
                evidence,
                extraction_result.extracted_documents,
                component_failures,
                rule_certainty_impact=0.05,
            ),
            component_failures=component_failures,
            extracted_document_data=extraction_result.extracted_documents,
        )

    vision_exclusion_reason = _vision_exclusion_reason(submission, text, policy)
    if vision_exclusion_reason:
        return _rejected(
            submission,
            trace,
            evidence,
            ["EXCLUDED_VISION_ITEM"],
            vision_exclusion_reason,
            confidence=_confidence_score(
                submission,
                evidence,
                extraction_result.extracted_documents,
                component_failures,
                rule_certainty_impact=0.05,
            ),
            component_failures=component_failures,
            extracted_document_data=extraction_result.extracted_documents,
        )

    waiting_reason = _waiting_period_reason(submission, member, text, policy)
    if waiting_reason:
        return _rejected(
            submission,
            trace,
            evidence,
            ["WAITING_PERIOD"],
            waiting_reason,
            confidence=_confidence_score(
                submission,
                evidence,
                extraction_result.extracted_documents,
                component_failures,
                rule_certainty_impact=-0.07,
            ),
            component_failures=component_failures,
            extracted_document_data=extraction_result.extracted_documents,
        )

    pre_auth_reason = _pre_auth_reason(submission, policy, claim_id)
    if pre_auth_reason:
        return _rejected(
            submission,
            trace,
            evidence,
            ["PRE_AUTH_MISSING"],
            pre_auth_reason,
            confidence=_confidence_score(
                submission,
                evidence,
                extraction_result.extracted_documents,
                component_failures,
                rule_certainty_impact=-0.08,
            ),
            component_failures=component_failures,
            extracted_document_data=extraction_result.extracted_documents,
            claim_id=claim_id,
        )

    fraud_reason = _fraud_reason(submission, policy)
    if fraud_reason:
        decision = ClaimDecision(
            decision=ClaimDecisionType.MANUAL_REVIEW,
            approved_amount=0,
            confidence_score=_confidence_score(
                submission,
                evidence,
                extraction_result.extracted_documents,
                component_failures,
                rule_certainty_impact=-0.14,
            ),
            reason=fraud_reason,
        )
        trace.append(
            TraceEvent(
                component="FraudSignalAgent",
                level=TraceLevel.WARNING,
                message="Claim routed to manual review due to fraud signals.",
                output_summary={"signals": [fraud_reason]},
                checks_performed=["same_day_claim_count", "high_value_manual_review_threshold"],
                confidence_impact=-0.14,
                warnings=[fraud_reason],
            )
        )
        return _completed_response(
            submission,
            decision,
            trace,
            evidence,
            component_failures,
            extraction_result.extracted_documents,
        )

    if (
        submission.claimed_amount > policy.coverage.per_claim_limit
        and submission.claim_category != "DENTAL"
    ):
        return _rejected(
            submission,
            trace,
            evidence,
            ["PER_CLAIM_EXCEEDED"],
            (
                f"Claimed amount INR {submission.claimed_amount:.0f} exceeds the per-claim "
                f"limit of INR {policy.coverage.per_claim_limit:.0f}."
            ),
            confidence=_confidence_score(
                submission,
                evidence,
                extraction_result.extracted_documents,
                component_failures,
                rule_certainty_impact=-0.06,
            ),
            component_failures=component_failures,
            extracted_document_data=extraction_result.extracted_documents,
        )

    annual_limit_reason = _annual_limit_reason(submission, policy)
    if annual_limit_reason:
        return _rejected(
            submission,
            trace,
            evidence,
            ["ANNUAL_OPD_LIMIT_EXCEEDED"],
            annual_limit_reason,
            confidence=_confidence_score(
                submission,
                evidence,
                extraction_result.extracted_documents,
                component_failures,
                rule_certainty_impact=-0.06,
            ),
            component_failures=component_failures,
            extracted_document_data=extraction_result.extracted_documents,
        )

    decision = _approve_or_partially_approve(submission, policy, confidence)
    if component_failures:
        decision.reason += " Manual review is recommended because processing completed with warnings."
    trace.append(
        TraceEvent(
            component="RuleEngine",
            message="Deterministic policy checks completed.",
            output_summary={
                "decision": decision.decision,
                "approved_amount": decision.approved_amount,
                "confidence_score": decision.confidence_score,
            },
            checks_performed=[
                "member_validity",
                "policy_validity",
                "submission_deadline",
                "minimum_claim_amount",
                "category_coverage",
                "exclusions",
                "waiting_periods",
                "pre_authorization",
                "fraud_thresholds",
                "per_claim_limit",
                "annual_opd_limit",
                "amount_calculation",
            ],
            evidence_ids=[item.evidence_id for item in evidence],
        )
    )
    return _completed_response(
        submission,
        decision,
        trace,
        evidence,
        component_failures,
        extraction_result.extracted_documents,
    )


def run_test_case_eval(policy: PolicyTerms | None = None) -> EvalRun:
    policy = policy or read_policy_terms()
    raw_cases = json.loads(TEST_CASES_PATH.read_text(encoding="utf-8"))["test_cases"]
    case_results: list[EvalCaseResult] = []

    for raw_case in raw_cases:
        submission = ClaimSubmission.model_validate(raw_case["input"])
        actual = process_claim(submission, policy)
        expected = raw_case["expected"]
        passed, failures = _evaluate_case(expected, actual)
        case_results.append(
            EvalCaseResult(
                case_id=raw_case["case_id"],
                case_name=raw_case["case_name"],
                passed=passed,
                expected=expected,
                actual=actual,
                notes=failures,
            )
        )

    passed_count = sum(1 for case in case_results if case.passed)
    rr_precision, rr_recall, rr_f1 = _rejection_reason_metrics(case_results)
    metrics = EvalMetrics(
        total_cases=len(case_results),
        completed_cases=len(case_results),
        decision_accuracy=passed_count / len(case_results),
        early_stop_accuracy=_early_stop_accuracy(case_results),
        approved_amount_exact_match_rate=_amount_match_rate(case_results),
        system_must_accuracy=_system_must_accuracy(case_results),
        rejection_reason_precision=rr_precision,
        rejection_reason_recall=rr_recall,
        rejection_reason_f1=rr_f1,
    )
    eval_run = EvalRun(
        status=ClaimStatus.COMPLETED,
        completed_at=datetime.now(timezone.utc),
        metrics=metrics,
        cases=case_results,
    )
    generate_eval_report(eval_run)
    return eval_run


def _validate_documents(
    submission: ClaimSubmission,
    policy: PolicyTerms,
    trace: list[TraceEvent],
    evidence: list[PolicyEvidence],
) -> ClaimResponse | None:
    requirement = policy.document_requirements[submission.claim_category]
    classifications = [classify_document(doc) for doc in submission.documents]
    uploaded_types = [item.classification.document_type for item in classifications]
    classification_summary = [
        {
            "file_id": item.document.file_id,
            "file_name": item.document.file_name,
            "document_type": item.classification.document_type,
            "confidence": item.classification.confidence,
            "source": item.source,
        }
        for item in classifications
    ]
    trace.append(
        TraceEvent(
            component="DocumentClassifier",
            message="Documents classified for early intake validation.",
            input_summary={
                "required_document_types": requirement.required,
                "uploaded_file_ids": [doc.file_id for doc in submission.documents],
            },
            output_summary={"classifications": classification_summary},
            checks_performed=["document_classification", "document_quality_available"],
            evidence_ids=[item.evidence_id for item in evidence if item.rule_category == "document_requirements"],
        )
    )

    unreadable = [item.document for item in classifications if item.document.quality == DocumentQuality.UNREADABLE]
    if unreadable:
        val_claim_id = f"CLM_{uuid4().hex[:12].upper()}"
        filename = unreadable[0].file_name or unreadable[0].file_id
        category_label = _readable_category(submission.claim_category)
        detail = _msg_unreadable(val_claim_id, category_label, filename)
        short_msg = f'The uploaded document "{filename}" is unreadable. Please re-upload a clearer image or PDF.'
        trace.append(
            TraceEvent(
                component="DocumentVerifierAgent",
                level=TraceLevel.WARNING,
                message=short_msg,
                output_summary={"affected_file_ids": [doc.file_id for doc in unreadable]},
                checks_performed=["readability_check"],
                confidence_impact=-0.35,
                warnings=[short_msg],
            )
        )
        return ClaimResponse(
            claim_id=val_claim_id,
            status=ClaimStatus.ACTION_REQUIRED,
            submission=submission,
            reason=detail,
            member_action_required=MemberActionRequired(
                code="UNREADABLE_DOCUMENT",
                message=detail,
                affected_file_ids=[doc.file_id for doc in unreadable],
            ),
            trace=trace,
            retrieved_policy_evidence=evidence,
        )

    unknown = [item for item in classifications if item.classification.document_type == DocumentType.UNKNOWN]
    if unknown:
        val_claim_id = f"CLM_{uuid4().hex[:12].upper()}"
        category_label = _readable_category(submission.claim_category)
        uploaded_items = [
            (item.document.file_name or item.document.file_id, _readable_doc_type(str(item.classification.document_type)))
            for item in unknown
        ]
        detail = _msg_wrong_doc_type(val_claim_id, category_label, uploaded_items, requirement.required)
        short_msg = (
            f"The uploaded document {_join_names(item.document.file_name or item.document.file_id for item in unknown)} "
            f"could not be identified as a supported document type."
        )
        trace.append(
            TraceEvent(
                component="DocumentVerifierAgent",
                level=TraceLevel.WARNING,
                message=short_msg,
                output_summary={"affected_file_ids": [item.document.file_id for item in unknown]},
                checks_performed=["supported_document_type_check"],
                confidence_impact=-0.25,
                warnings=[short_msg],
            )
        )
        return ClaimResponse(
            claim_id=val_claim_id,
            status=ClaimStatus.ACTION_REQUIRED,
            submission=submission,
            reason=detail,
            member_action_required=MemberActionRequired(
                code="WRONG_DOCUMENT_TYPE",
                message=detail,
                affected_file_ids=[item.document.file_id for item in unknown],
                required_document_types=requirement.required,
            ),
            trace=trace,
            retrieved_policy_evidence=evidence,
        )

    missing = [doc_type for doc_type in requirement.required if doc_type not in uploaded_types]
    if missing:
        val_claim_id = f"CLM_{uuid4().hex[:12].upper()}"
        category_label = _readable_category(submission.claim_category)
        member_name = _member_name(submission, policy)
        if len(missing) == 1:
            detail = _detailed_missing_doc_message(missing[0], submission.claim_category, val_claim_id, member_name)
            short_msg = (
                f"A {_readable_doc_type(str(missing[0]))} is required for {category_label} claims "
                f"but was not found among your uploads."
            )
        else:
            detail = _msg_multiple_missing(missing, val_claim_id, submission.claim_category)
            short_msg = (
                f"{_join_doc_types(missing)} are required for {category_label} claims "
                f"but were not found among your uploads."
            )
        trace.append(
            TraceEvent(
                component="DocumentVerifierAgent",
                level=TraceLevel.WARNING,
                message=short_msg,
                output_summary={"missing_document_types": missing, "uploaded_document_types": uploaded_types},
                checks_performed=["required_document_check"],
                evidence_ids=[item.evidence_id for item in evidence if item.rule_category == "document_requirements"],
                confidence_impact=-0.2,
                warnings=[short_msg],
            )
        )
        return ClaimResponse(
            claim_id=val_claim_id,
            status=ClaimStatus.ACTION_REQUIRED,
            submission=submission,
            reason=detail,
            member_action_required=MemberActionRequired(
                code="MISSING_REQUIRED_DOCUMENT",
                message=detail,
                required_document_types=missing,
            ),
            trace=trace,
            retrieved_policy_evidence=evidence,
        )

    patient_names_by_key: dict[str, list[str]] = {}
    patient_display_names: dict[str, str] = {}
    for doc in submission.documents:
        raw_name = doc.patient_name_on_doc or (doc.content or {}).get("patient_name")
        if not raw_name:
            continue
        name = str(raw_name).strip()
        key = re.sub(r"\s+", " ", name).casefold()
        patient_names_by_key.setdefault(key, []).append(doc.file_id)
        patient_display_names.setdefault(key, name)

    if len(patient_names_by_key) > 1:
        val_claim_id = f"CLM_{uuid4().hex[:12].upper()}"
        names = [patient_display_names[key] for key in sorted(patient_names_by_key)]
        affected_file_ids = [
            file_id for key in sorted(patient_names_by_key) for file_id in patient_names_by_key[key]
        ]
        category_label = _readable_category(submission.claim_category)
        policy_member_name = _member_name(submission, policy)
        dependents = _member_dependents(submission, policy)
        detail = _msg_patient_mismatch(val_claim_id, category_label, names, policy_member_name, submission.member_id, dependents)
        short_msg = (
            "Uploaded documents appear to belong to different patients: "
            f"{', '.join(names)}. Please upload documents for the same patient."
        )
        trace.append(
            TraceEvent(
                component="PatientConsistencyAgent",
                level=TraceLevel.WARNING,
                message=short_msg,
                output_summary={"patient_names": names, "affected_file_ids": affected_file_ids},
                checks_performed=["patient_consistency_check"],
                confidence_impact=-0.25,
                warnings=[short_msg],
            )
        )
        return ClaimResponse(
            claim_id=val_claim_id,
            status=ClaimStatus.ACTION_REQUIRED,
            submission=submission,
            reason=detail,
            member_action_required=MemberActionRequired(
                code="PATIENT_MISMATCH",
                message=detail,
                affected_file_ids=affected_file_ids,
            ),
            trace=trace,
            retrieved_policy_evidence=evidence,
        )

    trace.append(
        TraceEvent(
            component="DocumentVerifierAgent",
            message="Required documents are present, readable, and patient names are consistent.",
            input_summary={"required_document_types": requirement.required},
            output_summary={"document_types": uploaded_types},
            checks_performed=[
                "required_document_check",
                "readability_check",
                "supported_document_type_check",
                "patient_consistency_check",
            ],
            evidence_ids=[item.evidence_id for item in evidence if item.rule_category == "document_requirements"],
        )
    )
    return None


def _patient_name_matches_member_family_reason(
    submission: ClaimSubmission,
    member: PolicyMember | None,
    policy: PolicyTerms,
    extracted_documents: list[ExtractedDocumentData],
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

    allowed_display = sorted({_normalize_name(name) for name in allowed_names.values()})
    return (
        "Uploaded documents mention patient "
        f"{', '.join(unrecognized)}, but the selected member {submission.member_id} only covers "
        f"{', '.join(allowed_display)}."
    )


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
    return _dedupe_names(names)


def _approve_or_partially_approve(
    submission: ClaimSubmission, policy: PolicyTerms, confidence: float
) -> ClaimDecision:
    category_config = policy.opd_categories[submission.claim_category.lower()]
    line_items = _line_items(submission)

    if submission.claim_category == "DENTAL":
        excluded = {item.lower() for item in (category_config.excluded_procedures or [])}
        decisions: list[LineItemDecision] = []
        approved_amount = 0.0
        for item in line_items:
            description = str(item.get("description", "Line item"))
            amount = float(item.get("amount", 0))
            is_excluded = any(term in description.lower() for term in excluded)
            if is_excluded:
                decisions.append(
                    LineItemDecision(
                        description=description,
                        claimed_amount=amount,
                        approved_amount=0,
                        decision=LineItemDecisionType.REJECTED,
                        reason="Excluded cosmetic dental procedure.",
                    )
                )
            else:
                approved_amount += amount
                decisions.append(
                    LineItemDecision(
                        description=description,
                        claimed_amount=amount,
                        approved_amount=amount,
                        decision=LineItemDecisionType.APPROVED,
                        reason="Covered dental procedure.",
                    )
                )
        decision_type = ClaimDecisionType.PARTIAL if approved_amount < submission.claimed_amount else ClaimDecisionType.APPROVED
        rejection_reasons = ["EXCLUDED_DENTAL_PROCEDURE"] if approved_amount == 0 else []
        if approved_amount == 0:
            decision_type = ClaimDecisionType.REJECTED
        return ClaimDecision(
            decision=decision_type,
            approved_amount=approved_amount,
            confidence_score=confidence,
            reason="Covered dental items were approved and excluded cosmetic items were rejected.",
            rejection_reasons=rejection_reasons,
            line_item_decisions=decisions,
        )

    base_amount = submission.claimed_amount
    hospital = submission.hospital_name or _hospital_name(submission)
    parts: list[str] = []
    if hospital in policy.network_hospitals and category_config.network_discount_percent:
        discount = base_amount * category_config.network_discount_percent / 100
        base_amount -= discount
        parts.append(
            f"Network discount {category_config.network_discount_percent:.0f}% applied before co-pay."
        )
    if category_config.copay_percent:
        copay = base_amount * category_config.copay_percent / 100
        base_amount -= copay
        parts.append(f"Co-pay {category_config.copay_percent:.0f}% deducted.")

    reason = " ".join(parts) or "Claim satisfies deterministic policy checks."
    return ClaimDecision(
        decision=ClaimDecisionType.APPROVED,
        approved_amount=round(base_amount, 2),
        confidence_score=confidence,
        reason=reason,
        line_item_decisions=[
            LineItemDecision(
                description="Claim total",
                claimed_amount=submission.claimed_amount,
                approved_amount=round(base_amount, 2),
                decision=LineItemDecisionType.APPROVED,
                reason=reason,
            )
        ],
    )


def _rejected(
    submission: ClaimSubmission,
    trace: list[TraceEvent],
    evidence: list[PolicyEvidence],
    rejection_reasons: list[str],
    reason: str,
    confidence: float,
    component_failures: list[ComponentFailure] | None = None,
    extracted_document_data: list[ExtractedDocumentData] | None = None,
    claim_id: str | None = None,
) -> ClaimResponse:
    decision = ClaimDecision(
        decision=ClaimDecisionType.REJECTED,
        approved_amount=0,
        confidence_score=confidence,
        reason=reason,
        rejection_reasons=rejection_reasons,
    )
    trace.append(
        TraceEvent(
            component="RuleEngine",
            level=TraceLevel.WARNING,
            message=reason,
            output_summary={"rejection_reasons": rejection_reasons},
            checks_performed=_rule_checks_for_rejection(rejection_reasons),
            evidence_ids=[item.evidence_id for item in evidence],
            confidence_impact=round(confidence - 0.97, 4),
            warnings=[reason],
        )
    )
    return _completed_response(
        submission,
        decision,
        trace,
        evidence,
        component_failures or [],
        extracted_document_data or [],
        claim_id=claim_id,
    )


def _completed_response(
    submission: ClaimSubmission,
    decision: ClaimDecision,
    trace: list[TraceEvent],
    evidence: list[PolicyEvidence],
    component_failures: list[ComponentFailure],
    extracted_document_data: list[ExtractedDocumentData] | None = None,
    claim_id: str | None = None,
) -> ClaimResponse:
    extracted_documents = extracted_document_data or []
    trace.extend(
        _final_explainability_trace(
            submission,
            decision,
            evidence,
            component_failures,
            extracted_documents,
        )
    )
    extra: dict[str, Any] = {"claim_id": claim_id} if claim_id is not None else {}
    return ClaimResponse(
        **extra,
        status=ClaimStatus.COMPLETED,
        submission=submission,
        decision=decision,
        approved_amount=decision.approved_amount,
        confidence_score=decision.confidence_score,
        reason=decision.reason,
        rejection_reasons=decision.rejection_reasons,
        line_item_decisions=decision.line_item_decisions,
        extracted_document_data=extracted_documents,
        trace=trace,
        retrieved_policy_evidence=evidence,
        component_failures=component_failures,
    )


def _final_explainability_trace(
    submission: ClaimSubmission,
    decision: ClaimDecision,
    evidence: list[PolicyEvidence],
    component_failures: list[ComponentFailure],
    extracted_documents: list[ExtractedDocumentData],
) -> list[TraceEvent]:
    confidence_inputs = _confidence_inputs(
        submission,
        evidence,
        extracted_documents,
        component_failures,
    )
    amount_calculation = _amount_calculation_summary(submission, decision)
    evidence_ids = [item.evidence_id for item in evidence]
    return [
        TraceEvent(
            component="ConfidenceScorer",
            message="Final confidence score computed from document, extraction, policy, rule, and component signals.",
            input_summary=confidence_inputs,
            output_summary={
                "confidence_score": decision.confidence_score,
                "decision": decision.decision,
            },
            checks_performed=[
                "document_quality",
                "extraction_completeness",
                "patient_consistency",
                "policy_evidence_strength",
                "rule_certainty",
                "component_failures",
            ],
            evidence_ids=evidence_ids,
            confidence_impact=round(decision.confidence_score - 0.97, 4),
            warnings=[failure.message for failure in component_failures],
        ),
        TraceEvent(
            component="DecisionExplainer",
            message="Decision explanation assembled for review.",
            input_summary={
                "documents_checked": _document_check_summary(submission),
                "extracted_fields": _extracted_field_summary(extracted_documents),
                "policy_rules_applied": _policy_rule_summary(evidence),
            },
            output_summary={
                "decision": decision.decision,
                "approved_amount": decision.approved_amount,
                "rejection_reasons": decision.rejection_reasons,
                "line_item_decisions": [
                    item.model_dump(mode="json") for item in decision.line_item_decisions
                ],
                "amount_calculation": amount_calculation,
                "reason": decision.reason,
            },
            checks_performed=[
                "documents_checked_summary",
                "fields_extracted_summary",
                "policy_rules_applied_summary",
                "passed_failed_rule_summary",
                "approved_amount_calculation_summary",
                "confidence_change_summary",
            ],
            evidence_ids=evidence_ids,
            warnings=[failure.message for failure in component_failures],
        ),
    ]


def _confidence_score(
    submission: ClaimSubmission,
    evidence: list[PolicyEvidence],
    extracted_documents: list[ExtractedDocumentData],
    component_failures: list[ComponentFailure] | None = None,
    *,
    rule_certainty_impact: float = 0,
) -> float:
    inputs = _confidence_inputs(submission, evidence, extracted_documents, component_failures or [])
    score = 0.97
    score += inputs["document_quality_impact"]
    score += inputs["extraction_completeness_impact"]
    score += inputs["policy_evidence_impact"]
    score += rule_certainty_impact
    score += inputs["component_failure_impact"]
    return round(max(0.5, min(0.99, score)), 2)


def _confidence_inputs(
    submission: ClaimSubmission,
    evidence: list[PolicyEvidence],
    extracted_documents: list[ExtractedDocumentData],
    component_failures: list[ComponentFailure],
) -> dict[str, Any]:
    qualities = [document.quality for document in submission.documents]
    low_quality_count = sum(1 for quality in qualities if quality == DocumentQuality.LOW)
    unknown_quality_count = sum(1 for quality in qualities if quality == DocumentQuality.UNKNOWN)
    unreadable_count = sum(1 for quality in qualities if quality == DocumentQuality.UNREADABLE)
    # None means quality was not assessed (fixtures, pre-parsed uploads) — no penalty applied
    missing_field_count = sum(len(item.missing_fields) for item in extracted_documents)
    average_extraction_confidence = (
        sum(item.confidence for item in extracted_documents) / len(extracted_documents)
        if extracted_documents
        else 0
    )
    evidence_strength = (
        max((item.rrf_score or item.dense_score or item.lexical_score or 0) for item in evidence)
        if evidence
        else 0
    )

    document_quality_impact = (
        -0.35 * unreadable_count
        - 0.05 * low_quality_count
        - 0.02 * unknown_quality_count
    )
    extraction_completeness_impact = 0.0
    if extracted_documents:
        extraction_completeness_impact -= min(0.14, 0.025 * missing_field_count)
        extraction_completeness_impact -= max(0.0, 0.9 - average_extraction_confidence) * 0.2
    policy_evidence_impact = 0.0 if evidence_strength >= 0.02 else -0.04
    component_failure_impact = -0.08 * len(component_failures)

    return {
        "document_quality": [str(quality) for quality in qualities],
        "document_quality_impact": round(document_quality_impact, 4),
        "extracted_document_count": len(extracted_documents),
        "missing_field_count": missing_field_count,
        "average_extraction_confidence": round(average_extraction_confidence, 4),
        "extraction_completeness_impact": round(extraction_completeness_impact, 4),
        "patient_consistency": "passed",
        "policy_evidence_count": len(evidence),
        "strongest_policy_evidence_score": round(evidence_strength, 6),
        "policy_evidence_impact": round(policy_evidence_impact, 4),
        "component_failure_count": len(component_failures),
        "component_failure_impact": round(component_failure_impact, 4),
    }


def _document_check_summary(submission: ClaimSubmission) -> list[dict[str, Any]]:
    return [
        {
            "file_id": document.file_id,
            "file_name": document.file_name,
            "declared_type": document.declared_type,
            "actual_type": document.actual_type,
            "quality": document.quality,
        }
        for document in submission.documents
    ]


def _extracted_field_summary(extracted_documents: list[ExtractedDocumentData]) -> list[dict[str, Any]]:
    return [
        {
            "file_id": item.file_id,
            "document_type": item.document_type,
            "fields": sorted(item.fields),
            "missing_fields": item.missing_fields,
            "confidence": item.confidence,
            "warnings": item.warnings,
        }
        for item in extracted_documents
    ]


def _policy_rule_summary(evidence: list[PolicyEvidence]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": item.evidence_id,
            "rule_category": item.rule_category,
            "source_path": item.source_path,
            "rrf_score": item.rrf_score,
        }
        for item in evidence
    ]


def _amount_calculation_summary(submission: ClaimSubmission, decision: ClaimDecision) -> dict[str, Any]:
    return {
        "claimed_amount": submission.claimed_amount,
        "approved_amount": decision.approved_amount,
        "line_items": [
            {
                "description": item.description,
                "claimed_amount": item.claimed_amount,
                "approved_amount": item.approved_amount,
                "decision": item.decision,
                "reason": item.reason,
            }
            for item in decision.line_item_decisions
        ],
    }


def _rule_checks_for_rejection(rejection_reasons: list[str]) -> list[str]:
    checks_by_reason = {
        "POLICY_MISMATCH": ["policy_id_matches_active_policy"],
        "MEMBER_NOT_FOUND": ["member_validity"],
        "POLICY_NOT_ACTIVE": ["policy_validity"],
        "SUBMISSION_RULE_FAILED": ["submission_deadline", "minimum_claim_amount"],
        "CATEGORY_NOT_COVERED": ["category_coverage"],
        "EXCLUDED_CONDITION": ["policy_exclusions"],
        "EXCLUDED_VISION_ITEM": ["vision_exclusions"],
        "WAITING_PERIOD": ["waiting_periods"],
        "PRE_AUTH_MISSING": ["pre_authorization"],
        "PER_CLAIM_EXCEEDED": ["per_claim_limit"],
        "ANNUAL_OPD_LIMIT_EXCEEDED": ["annual_opd_limit"],
        "EXCLUDED_DENTAL_PROCEDURE": ["dental_excluded_procedures"],
    }
    checks: list[str] = []
    for reason in rejection_reasons:
        checks.extend(checks_by_reason.get(reason, ["deterministic_rule_check"]))
    return checks


def _member_for(member_id: str, policy: PolicyTerms) -> PolicyMember | None:
    return next((member for member in policy.members if member.member_id == member_id), None)


def _action_required_response(
    submission: ClaimSubmission,
    trace: list[TraceEvent],
    evidence: list[PolicyEvidence],
    reason: str,
    *,
    code: str,
    claim_id: str | None = None,
    component_failures: list[ComponentFailure] | None = None,
    extracted_document_data: list[ExtractedDocumentData] | None = None,
    required_document_types: list[DocumentType] | None = None,
) -> ClaimResponse:
    affected_file_ids = [item.file_id for item in extracted_document_data or []] or [
        document.file_id for document in submission.documents
    ]
    extra: dict[str, Any] = {"claim_id": claim_id} if claim_id is not None else {}
    return ClaimResponse(
        **extra,
        status=ClaimStatus.ACTION_REQUIRED,
        submission=submission,
        reason=reason,
        member_action_required=MemberActionRequired(
            code=code,
            message=reason,
            affected_file_ids=affected_file_ids,
            required_document_types=required_document_types or [],
        ),
        trace=trace,
        retrieved_policy_evidence=evidence,
        component_failures=component_failures or [],
        extracted_document_data=extracted_document_data or [],
    )


def _patient_name_matches_member_family_reason(
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
    dependents = _member_dependents(submission, policy)
    return _msg_patient_mismatch(
        claim_id,
        category_label,
        unrecognized,
        member.name,
        submission.member_id,
        dependents,
    )


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


def _policy_validity_reason(submission: ClaimSubmission, policy: PolicyTerms) -> str | None:
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


def _submission_rules_reason(submission: ClaimSubmission, policy: PolicyTerms, claim_id: str) -> str | None:
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
        )
    return None


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


def _category_coverage_reason(submission: ClaimSubmission, policy: PolicyTerms) -> str | None:
    config = policy.opd_categories[submission.claim_category.lower()]
    if not config.covered:
        return f"{submission.claim_category} claims are not covered under policy {policy.policy_id}."
    return None


def _annual_limit_reason(submission: ClaimSubmission, policy: PolicyTerms) -> str | None:
    ytd_claims = submission.ytd_claims_amount or 0
    projected_total = ytd_claims + submission.claimed_amount
    if projected_total > policy.coverage.annual_opd_limit:
        return (
            f"Projected annual OPD claims would be INR {projected_total:.0f}, exceeding the annual "
            f"OPD limit of INR {policy.coverage.annual_opd_limit:.0f}."
        )
    return None


def _claim_text(submission: ClaimSubmission) -> str:
    return json.dumps([doc.content or {} for doc in submission.documents], sort_keys=True).lower()


def _exclusion_reason(text: str, policy: PolicyTerms) -> str | None:
    for term in policy.exclusions.conditions:
        normalized = term.lower()
        if "obesity" in normalized and ("obesity" in text or "bariatric" in text or "diet" in text):
            return f"Treatment is excluded under policy exclusion: {term}."
        if normalized in text:
            return f"Treatment is excluded under policy exclusion: {term}."
    return None


def _vision_exclusion_reason(submission: ClaimSubmission, text: str, policy: PolicyTerms) -> str | None:
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


def _waiting_period_reason(
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
            eligible_from = member.join_date.toordinal() + days
            eligible_date = date.fromordinal(eligible_from)
            if submission.treatment_date < eligible_date:
                return (
                    f"{condition_text.title()} treatment is in the {days}-day waiting period. "
                    f"Member is eligible for this condition from {eligible_date.isoformat()}."
                )
    return None


def _pre_auth_reason(submission: ClaimSubmission, policy: PolicyTerms, claim_id: str) -> str | None:
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


def _fraud_reason(submission: ClaimSubmission, policy: PolicyTerms) -> str | None:
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


def _line_items(submission: ClaimSubmission) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for doc in submission.documents:
        content = doc.content or {}
        items.extend(content.get("line_items", []))
        if "test_name" in content:
            items.append({"description": content["test_name"], "amount": submission.claimed_amount})
    return items or [{"description": "Claim total", "amount": submission.claimed_amount}]


def _hospital_name(submission: ClaimSubmission) -> str | None:
    for doc in submission.documents:
        content = doc.content or {}
        if "hospital_name" in content:
            return str(content["hospital_name"])
    return None


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


def _policy_evidence(submission: ClaimSubmission, policy: PolicyTerms) -> list[PolicyEvidence]:
    evidence = retrieve_policy_evidence(submission, policy)
    if evidence:
        return evidence

    return [
        PolicyEvidence(
            evidence_id="POLICY_DOCUMENT_REQUIREMENTS",
            source="policy_terms.json",
            source_path=f"document_requirements.{submission.claim_category}",
            rule_category="document_requirements",
            claim_category=submission.claim_category,
            text=(
                f"{submission.claim_category} requires "
                f"{policy.document_requirements[submission.claim_category].required}."
            ),
            rrf_score=1.0,
        ),
        PolicyEvidence(
            evidence_id="POLICY_CATEGORY_RULES",
            source="policy_terms.json",
            source_path=f"opd_categories.{submission.claim_category.lower()}",
            rule_category="opd_category",
            claim_category=submission.claim_category,
            text=str(policy.opd_categories[submission.claim_category.lower()].model_dump(mode="json")),
            rrf_score=0.95,
        ),
    ]


def _evaluate_case(expected: dict[str, Any], actual: ClaimResponse) -> tuple[bool, list[str]]:
    """Return (passed, failed_notes) where failed_notes lists every requirement that was not met."""
    failures: list[str] = []

    # ── core decision checks ──────────────────────────────────────────────────
    if expected.get("decision") is None:
        if not (actual.status == ClaimStatus.ACTION_REQUIRED and actual.decision is None):
            failures.append(
                f"Expected early stop (ACTION_REQUIRED, no decision) "
                f"but got status={actual.status} decision={actual.decision}"
            )
    else:
        if actual.decision is None:
            failures.append(f"Expected decision={expected['decision']} but got no decision")
        elif actual.decision.decision != expected["decision"]:
            failures.append(
                f"Expected decision={expected['decision']} "
                f"but got {actual.decision.decision}"
            )

        if "approved_amount" in expected and actual.approved_amount != expected["approved_amount"]:
            failures.append(
                f"Expected approved_amount={expected['approved_amount']} "
                f"but got {actual.approved_amount}"
            )

        for reason_code in expected.get("rejection_reasons", []):
            if reason_code not in actual.rejection_reasons:
                failures.append(f"Missing rejection reason: {reason_code}")

        if expected.get("confidence_score") == "above 0.90" and (actual.confidence_score or 0) <= 0.9:
            failures.append(
                f"Expected confidence > 0.90 but got {actual.confidence_score}"
            )
        if expected.get("confidence_score") == "above 0.85" and (actual.confidence_score or 0) <= 0.85:
            failures.append(
                f"Expected confidence > 0.85 but got {actual.confidence_score}"
            )

    # ── system_must checks ────────────────────────────────────────────────────
    for requirement in expected.get("system_must", []):
        failure = _check_system_must(requirement, actual)
        if failure:
            failures.append(failure)

    return len(failures) == 0, failures


def _check_system_must(requirement: str, actual: ClaimResponse) -> str | None:
    """Return a failure message if the requirement is not met, else None."""
    req = requirement.lower()
    reason_text = (actual.reason or "").lower()
    mar = actual.member_action_required

    # TC001 / TC002 / TC003 — early stop requirements
    if "stop before making any claim decision" in req:
        if not (actual.status == ClaimStatus.ACTION_REQUIRED and actual.decision is None):
            return f"FAIL: '{requirement}' — claim was not stopped early"

    if "name the uploaded document type and the required document type" in req or \
       "specifically what document type was uploaded and what is needed instead" in req:
        if mar is None:
            return f"FAIL: '{requirement}' — member_action_required is absent"
        has_uploaded = any(
            dt.lower() in (mar.message or "").lower() or dt.lower() in reason_text
            for dt in ["prescription", "hospital_bill", "lab_report", "diagnostic_report",
                       "pharmacy_bill", "discharge_summary", "dental_report"]
        )
        has_required = bool(mar.required_document_types)
        if not has_uploaded or not has_required:
            return (
                f"FAIL: '{requirement}' — message does not name both uploaded and required doc types"
            )

    if "identify that the pharmacy bill cannot be read" in req:
        if mar is None or mar.code != "UNREADABLE_DOCUMENT":
            return f"FAIL: '{requirement}' — code is {mar.code if mar else 'absent'}, expected UNREADABLE_DOCUMENT"

    if "ask the member to re-upload that specific document" in req:
        if mar is None or not mar.affected_file_ids:
            return f"FAIL: '{requirement}' — affected_file_ids is empty; specific document not identified"

    if "not reject the claim outright" in req:
        if actual.decision and actual.decision.decision == ClaimDecisionType.REJECTED:
            return f"FAIL: '{requirement}' — claim was outright rejected"

    if "detect that the documents belong to different people" in req:
        if mar is None or mar.code != "PATIENT_MISMATCH":
            return f"FAIL: '{requirement}' — code is {mar.code if mar else 'absent'}, expected PATIENT_MISMATCH"

    if "surface this to the member with the specific names" in req:
        # TC003 documents have patient_name_on_doc "Rajesh Kumar" and "Arjun Mehta"
        names_in_message = sum(
            1 for name in ["rajesh", "arjun", "kumar", "mehta"]
            if name in (mar.message if mar else "").lower() or name in reason_text
        )
        if names_in_message < 2:
            return f"FAIL: '{requirement}' — patient names not surfaced in message or reason"

    if "not proceed to a claim decision" in req:
        if actual.decision is not None:
            return f"FAIL: '{requirement}' — a claim decision was produced"

    # TC005 — waiting period eligibility date
    if "date from which the member will be eligible" in req:
        has_date = bool(re.search(r"\d{4}-\d{2}-\d{2}", reason_text)) or \
                   any(
                       word in reason_text
                       for word in ["eligible", "eligib"]
                   )
        if not has_date:
            return f"FAIL: '{requirement}' — eligibility date not found in reason"

    # TC006 — line-item itemization
    if "itemize which line items were approved and which were rejected" in req:
        if not actual.line_item_decisions:
            return f"FAIL: '{requirement}' — line_item_decisions is empty"

    if "state the reason for each rejection at the line-item level" in req:
        bad = [
            item.description
            for item in actual.line_item_decisions
            if item.decision in (LineItemDecisionType.REJECTED, LineItemDecisionType.ADJUSTED)
            and not item.reason.strip()
        ]
        if bad:
            return f"FAIL: '{requirement}' — items without reason: {bad}"

    # TC007 — pre-authorization
    if "pre-authorization was required and not obtained" in req:
        has_preauth = any(
            kw in reason_text
            for kw in ["pre-authorization", "pre_authorization", "preauthorization", "pre-auth"]
        )
        if not has_preauth:
            return f"FAIL: '{requirement}' — pre-authorization not mentioned in reason"

    if "what they should do to resubmit with pre-auth" in req:
        has_action = any(
            kw in reason_text
            for kw in ["resubmit", "obtain", "valid pre-auth", "authorization"]
        )
        if not has_action:
            return f"FAIL: '{requirement}' — no resubmission instruction in reason"

    # TC008 — per-claim limit amounts
    if "state the per-claim limit and the claimed amount clearly" in req:
        has_two_amounts = len(re.findall(r"\d[\d,]+", reason_text)) >= 2
        if not has_two_amounts:
            return f"FAIL: '{requirement}' — reason does not contain both limit and claimed amounts"

    # TC009 — fraud / same-day
    if "flag the unusual same-day claim pattern" in req:
        has_sameday = any(
            kw in reason_text for kw in ["same-day", "same day", "same_day"]
        )
        if not has_sameday:
            return f"FAIL: '{requirement}' — same-day pattern not mentioned in reason"

    if "route to manual review rather than auto-rejecting" in req:
        if actual.decision and actual.decision.decision != ClaimDecisionType.MANUAL_REVIEW:
            return f"FAIL: '{requirement}' — decision is {actual.decision.decision}, not MANUAL_REVIEW"

    if "include the specific signals that triggered the flag" in req:
        if len(reason_text) < 30:
            return f"FAIL: '{requirement}' — reason is too short to include specific signals"

    # TC010 — network discount order
    if "apply network discount before co-pay, not after" in req:
        # Verified by amount: 4000 * 0.90 * 0.90 = 3240 (discount first, then copay)
        # vs 4000 * (1 - 0.10 - 0.10) = 3200 (wrong: subtract both together)
        if actual.approved_amount is not None and abs(actual.approved_amount - 3240.0) > 0.01:
            return (
                f"FAIL: '{requirement}' — approved_amount={actual.approved_amount}, "
                f"expected 3240.0 (discount before co-pay)"
            )

    if "show the breakdown of discount and co-pay in the decision output" in req:
        breakdown_text = reason_text + " ".join(
            item.reason.lower() for item in actual.line_item_decisions
        )
        has_discount = any(kw in breakdown_text for kw in ["discount", "co-pay", "copay"])
        if not has_discount:
            return f"FAIL: '{requirement}' — discount/co-pay breakdown absent from reason"

    # TC011 — component failure / graceful degradation
    if "not crash or return a 500 error" in req:
        # If we have an actual response object this check trivially passes.
        pass

    if "indicate in the output that a component failed and was skipped" in req:
        if not actual.component_failures:
            return f"FAIL: '{requirement}' — component_failures is empty"

    if "return a confidence score lower than a normal full-pipeline approval" in req:
        if (actual.confidence_score or 1.0) >= 0.9:
            return (
                f"FAIL: '{requirement}' — confidence_score={actual.confidence_score} "
                f"is not lower than a full-pipeline approval"
            )

    if "manual review is recommended due to incomplete processing" in req:
        if "manual review" not in reason_text:
            return f"FAIL: '{requirement}' — 'manual review' not mentioned in reason"

    return None


def _case_passed(expected: dict[str, Any], actual: ClaimResponse) -> bool:
    passed, _ = _evaluate_case(expected, actual)
    return passed


def _early_stop_accuracy(case_results: list[EvalCaseResult]) -> float:
    early_cases = [case for case in case_results if case.expected.get("decision") is None]
    return sum(1 for case in early_cases if case.passed) / len(early_cases)


def _amount_match_rate(case_results: list[EvalCaseResult]) -> float:
    amount_cases = [case for case in case_results if "approved_amount" in case.expected]
    return sum(1 for case in amount_cases if case.passed) / len(amount_cases)


def _system_must_accuracy(case_results: list[EvalCaseResult]) -> float:
    total = sum(len(case.expected.get("system_must", [])) for case in case_results)
    if total == 0:
        return 1.0
    failed = sum(
        sum(1 for note in case.notes if note.startswith("FAIL:"))
        for case in case_results
    )
    return (total - failed) / total


def _rejection_reason_metrics(case_results: list[EvalCaseResult]) -> tuple[float, float, float]:
    """Macro-averaged precision, recall, F1 over rejection reason label codes."""
    cases = [c for c in case_results if c.expected.get("rejection_reasons")]
    if not cases:
        return 1.0, 1.0, 1.0

    total_precision = 0.0
    total_recall = 0.0
    for case in cases:
        expected_set = set(case.expected["rejection_reasons"])
        actual_set = set(case.actual.rejection_reasons if case.actual else [])
        tp = len(expected_set & actual_set)
        precision = tp / len(actual_set) if actual_set else 0.0
        recall = tp / len(expected_set) if expected_set else 1.0
        total_precision += precision
        total_recall += recall

    macro_p = total_precision / len(cases)
    macro_r = total_recall / len(cases)
    f1 = (2 * macro_p * macro_r / (macro_p + macro_r)) if (macro_p + macro_r) > 0 else 0.0
    return round(macro_p, 4), round(macro_r, 4), round(f1, 4)


def generate_eval_report(eval_run: "EvalRun", output_path: Path | None = None) -> str:
    """Generate a Markdown eval report and write it to docs/eval_report.md."""
    from app.models import EvalRun as _EvalRun  # local import to avoid circular at module level

    out_path = output_path or (DOCS_DIR / "eval_report.md")
    m = eval_run.metrics
    lines: list[str] = []

    lines += [
        "# Eval Report",
        "",
        f"Generated: {eval_run.completed_at.strftime('%Y-%m-%d %H:%M UTC') if eval_run.completed_at else 'unknown'}  ",
        f"Eval run ID: `{eval_run.eval_run_id}`  ",
        f"Cases: {m.completed_cases}/{m.total_cases}",
        "",
        "## Aggregate Metrics",
        "",
        "| Metric | Value | Notes |",
        "| --- | ---: | --- |",
        f"| Decision accuracy | {_pct(m.decision_accuracy)} | Correct decision type out of all cases |",
        f"| Early-stop accuracy | {_pct(m.early_stop_accuracy)} | ACTION_REQUIRED returned correctly before adjudication |",
        f"| Approved amount exact match | {_pct(m.approved_amount_exact_match_rate)} | Applies to {sum(1 for c in eval_run.cases if 'approved_amount' in c.expected)} cases |",
        f"| System-must accuracy | {_pct(m.system_must_accuracy)} | Behavioural requirements across all system_must items |",
        f"| Rejection reason precision | {_pct(m.rejection_reason_precision)} | Macro-avg over {sum(1 for c in eval_run.cases if c.expected.get('rejection_reasons'))} cases with expected labels |",
        f"| Rejection reason recall | {_pct(m.rejection_reason_recall)} | Macro-avg |",
        f"| Rejection reason F1 | {_pct(m.rejection_reason_f1)} | Harmonic mean of precision and recall |",
        "",
        "> Retrieval precision@k, recall@k, MRR, NDCG are not computed: `test_cases.json` contains",
        "> no `expected_evidence_ids` field, so ground-truth evidence labels do not exist.",
        "",
        "---",
        "",
        "## Per-Case Results",
        "",
    ]

    for case in eval_run.cases:
        status_icon = "✅" if case.passed else "❌"
        actual = case.actual
        exp = case.expected

        actual_decision = actual.decision.decision if actual and actual.decision else None
        actual_status = actual.status if actual else "N/A"
        actual_amount = actual.approved_amount if actual else None
        actual_confidence = actual.confidence_score if actual else None

        lines += [
            f"### {status_icon} {case.case_id} — {case.case_name}",
            "",
            "**Input summary**",
            "",
        ]

        if actual and actual.submission:
            sub = actual.submission
            lines += [
                f"- Member: `{sub.member_id}` · Policy: `{sub.policy_id}`",
                f"- Category: `{sub.claim_category}` · Treatment date: `{sub.treatment_date}`",
                f"- Claimed amount: INR {sub.claimed_amount:,.0f}",
                f"- Hospital: {sub.hospital_name or '—'}",
            ]
            if sub.documents:
                doc_list = ", ".join(
                    f"`{d.file_id}` ({d.declared_type or 'UNKNOWN'})"
                    for d in sub.documents
                )
                lines.append(f"- Documents: {doc_list}")

        lines += ["", "**Expected vs actual**", ""]
        lines.append("| Field | Expected | Actual |")
        lines.append("| --- | --- | --- |")
        lines.append(f"| Decision | `{exp.get('decision', 'early stop')}` | `{actual_decision or actual_status}` |")
        if "approved_amount" in exp:
            actual_amount_str = f"INR {actual_amount:,.0f}" if actual_amount is not None else "—"
            lines.append(f"| Approved amount | INR {exp['approved_amount']:,} | {actual_amount_str} |")
        if exp.get("rejection_reasons"):
            exp_rr = ", ".join(f"`{r}`" for r in exp["rejection_reasons"])
            act_rr = ", ".join(f"`{r}`" for r in (actual.rejection_reasons if actual else [])) or "—"
            lines.append(f"| Rejection reasons | {exp_rr} | {act_rr} |")
        if exp.get("confidence_score"):
            lines.append(f"| Confidence | {exp['confidence_score']} | {f'{actual_confidence:.2f}' if actual_confidence else '—'} |")

        if exp.get("system_must"):
            lines += ["", "**System-must checks**", ""]
            failures = {n for n in case.notes if n.startswith("FAIL:")}
            failure_reqs = {n.split("' —")[0].replace("FAIL: '", "") for n in failures}
            for req in exp["system_must"]:
                icon = "❌" if req in failure_reqs else "✅"
                lines.append(f"- {icon} {req}")

        if case.notes:
            lines += ["", "**Failures / notes**", ""]
            for note in case.notes:
                lines.append(f"- {note}")

        if actual and actual.trace:
            lines += ["", "**Trace summary**", ""]
            for i, event in enumerate(actual.trace, 1):
                impact = f" ({event.confidence_impact:+.2f})" if event.confidence_impact else ""
                lines.append(f"{i}. `{event.component}` [{event.level}]{impact} — {event.message}")

        lines += ["", "---", ""]

    report = "\n".join(lines)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
    except OSError:
        pass  # non-fatal: report is still returned as a string
    return report


def _pct(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else "—"


_DOC_TYPE_LABELS: dict[str, str] = {
    "PRESCRIPTION": "Prescription",
    "HOSPITAL_BILL": "Hospital Bill",
    "LAB_REPORT": "Lab Report",
    "DIAGNOSTIC_REPORT": "Diagnostic Report",
    "PHARMACY_BILL": "Pharmacy Bill",
    "DISCHARGE_SUMMARY": "Discharge Summary",
    "DENTAL_REPORT": "Dental Report",
    "UNKNOWN": "Unknown Document",
}

_CATEGORY_LABELS: dict[str, str] = {
    "CONSULTATION": "Consultation",
    "DIAGNOSTIC": "Diagnostic",
    "PHARMACY": "Pharmacy",
    "DENTAL": "Dental",
    "VISION": "Vision",
    "ALTERNATIVE_MEDICINE": "Alternative Medicine",
}


def _readable_doc_type(doc_type: str) -> str:
    return _DOC_TYPE_LABELS.get(str(doc_type).upper(), str(doc_type).replace("_", " ").title())


def _readable_category(category: Any) -> str:
    return _CATEGORY_LABELS.get(str(category).upper(), str(category).replace("_", " ").title())


def _join_doc_types(types: Any) -> str:
    labels = [_readable_doc_type(str(t)) for t in types]
    if len(labels) == 0:
        return ""
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def _join_names(names: Any) -> str:
    items = list(names)
    if len(items) == 0:
        return ""
    if len(items) == 1:
        return f'"{items[0]}"'
    return ", ".join(f'"{n}"' for n in items[:-1]) + f' and "{items[-1]}"'


# ── Member lookup helpers ──────────────────────────────────────────────────────


def _member_name(submission: ClaimSubmission, policy: PolicyTerms) -> str:
    for m in policy.members:
        if m.member_id == submission.member_id:
            return m.name
    return submission.member_id


def _member_dependents(submission: ClaimSubmission, policy: PolicyTerms) -> list[str]:
    member = _member_for(submission.member_id, policy)
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


# ── Detailed message builders ──────────────────────────────────────────────────


def _msg_missing_prescription(claim_id: str, claim_category: str, member_name: str) -> str:
    return (
        f"Claim cannot proceed — Doctor's Prescription missing.\n\n"
        f"Your {claim_category} claim (Claim ID: {claim_id}) requires a valid doctor's prescription\n"
        f"but none was found in your submission.\n\n"
        f"What qualifies as a valid prescription:\n"
        f"  \u2713 Issued by an MBBS or higher qualified doctor\n"
        f"  \u2713 Contains doctor's MCI/state registration number (e.g. KA/45678/2015)\n"
        f"  \u2713 Shows patient name matching your policy ({member_name})\n"
        f"  \u2713 Dated within 30 days of treatment\n"
        f"  \u2713 Includes diagnosis and treatment advised\n\n"
        f"What does NOT qualify:\n"
        f"  \u2717 Pharmacy receipts or bills\n"
        f"  \u2717 Lab reports or diagnostic reports\n"
        f"  \u2717 Discharge summaries (unless they contain Rx)\n"
        f"  \u2717 Prescriptions older than 30 days from treatment date\n\n"
        f"Submit your claim again with the prescription attached.\n"
        f"If your doctor issued a digital prescription, a clear screenshot or PDF is accepted."
    )


def _msg_missing_hospital_bill(claim_id: str, claim_category: str) -> str:
    return (
        f"Claim cannot proceed — Hospital Bill or Clinic Invoice missing.\n\n"
        f"Your {claim_category} claim (Claim ID: {claim_id}) requires an original itemised bill\n"
        f"from the treating facility.\n\n"
        f"What qualifies:\n"
        f"  \u2713 Printed or handwritten bill from the hospital or clinic\n"
        f"  \u2713 Shows facility name, address, and contact\n"
        f"  \u2713 Itemised charges (consultation fee, tests, procedures listed separately)\n"
        f"  \u2713 Patient name, date of visit, and treating doctor's name\n"
        f"  \u2713 Total amount paid with payment mode (Cash / UPI / Card)\n"
        f"  \u2713 Cashier signature or facility stamp\n\n"
        f"What does NOT qualify:\n"
        f"  \u2717 Payment SMS or UPI transaction screenshot alone\n"
        f"  \u2717 Prescription with amount written on it\n"
        f"  \u2717 Pharmacy bill (this is a separate document)\n"
        f"  \u2717 Lab report with charges mentioned informally\n\n"
        f"Note: Small clinics may issue handwritten bills \u2014 these are accepted\n"
        f"provided the facility name and date are clearly visible."
    )


def _msg_missing_lab_report(claim_id: str) -> str:
    return (
        f"Claim cannot proceed — Diagnostic Report missing.\n\n"
        f"Your Diagnostic claim (Claim ID: {claim_id}) requires the actual test report\n"
        f"from the laboratory or diagnostic centre.\n\n"
        f"What qualifies:\n"
        f"  \u2713 Printed report from the lab with lab name and address\n"
        f"  \u2713 Shows each test name, result, unit, and normal reference range\n"
        f"  \u2713 Signed or stamped by a qualified pathologist or radiologist\n"
        f"  \u2713 Includes sample collection date and report generation date\n"
        f"  \u2713 Patient name matches your policy record\n\n"
        f"What does NOT qualify:\n"
        f"  \u2717 Prescription that mentions tests ordered (not the report itself)\n"
        f"  \u2717 SMS or email summary of test results\n"
        f"  \u2717 A photo of the report that is too blurry to read values\n\n"
        f"NABL-accredited lab reports are preferred but not mandatory.\n"
        f"If your report spans multiple pages, upload all pages as a single PDF or multiple images."
    )


def _msg_missing_pharmacy_bill(claim_id: str) -> str:
    return (
        f"Claim cannot proceed — Pharmacy Bill missing.\n\n"
        f"Your Pharmacy claim (Claim ID: {claim_id}) requires an itemised bill\n"
        f"from a registered pharmacy.\n\n"
        f"What qualifies:\n"
        f"  \u2713 Bill from a pharmacy with a valid Drug Licence Number (e.g. KA-BLR-XXXX)\n"
        f"  \u2713 Lists each medicine by name, quantity, MRP, and amount charged\n"
        f"  \u2713 Shows pharmacist name or stamp\n"
        f"  \u2713 Date of purchase within 30 days of prescription date\n\n"
        f"What does NOT qualify:\n"
        f'  \u2717 Hospital bill that mentions "medicines" as a lump sum\n'
        f"  \u2717 Online pharmacy order confirmation without itemised breakup\n"
        f"  \u2717 Prescription alone (even if it shows drug names and doses)\n"
        f"  \u2717 Handwritten chit from a pharmacy without Drug Licence Number\n\n"
        f"Important: Medicines must be prescribed by a doctor.\n"
        f"Over-the-counter purchases without a prescription are not covered."
    )


def _msg_wrong_doc_type(
    claim_id: str,
    claim_category: str,
    uploaded_items: list[tuple[str, str]],
    required_types: list,
) -> str:
    if uploaded_items:
        filename, detected_type = uploaded_items[0]
        uploaded_line = f"  Uploaded:  {detected_type}  ({filename})"
    else:
        uploaded_line = "  Uploaded:  Unknown document"
    required_types_list = ", ".join(_readable_doc_type(str(t)) for t in required_types)
    return (
        f"Claim on hold \u2014 Incorrect document type detected.\n\n"
        f"We reviewed your upload for {claim_category} claim (Claim ID: {claim_id}) and found a mismatch:\n\n"
        f"{uploaded_line}\n"
        f"  Required:  {required_types_list}\n\n"
        f"This is a common mix-up. Here is how to tell them apart:\n\n"
        f"  Prescription  \u2192  Issued by your doctor. Shows diagnosis, medicines,\n"
        f"                   and doctor's registration number.\n"
        f"  Hospital Bill \u2192  Issued by the hospital or clinic. Shows charges,\n"
        f"                   bill number, and total amount paid.\n"
        f"  Lab Report    \u2192  Issued by the lab. Shows test results with\n"
        f"                   reference ranges and pathologist's signature.\n"
        f"  Pharmacy Bill \u2192  Issued by the pharmacy. Shows drug names,\n"
        f"                   quantities, MRP, and drug licence number.\n\n"
        f"Your uploaded file has been retained and may count as a supporting document\n"
        f"if applicable. Please add the correct document and resubmit."
    )


def _msg_unreadable(claim_id: str, claim_category: str, filename: str) -> str:
    return (
        f"Claim on hold \u2014 Document could not be read.\n\n"
        f"The document you uploaded for {claim_category} claim (Claim ID: {claim_id}) could not be\n"
        f"processed because it is unclear.\n\n"
        f"File: {filename}\n\n"
        f"What to reupload:\n"
        f"  \u2713 Photograph in good lighting, without shadows or glare\n"
        f"  \u2713 All four corners of the document must be visible\n"
        f"  \u2713 Minimum resolution: 300 DPI or a standard smartphone camera photo\n"
        f"  \u2713 If stamped over critical text, request a re-stamped copy from\n"
        f"    the issuing doctor or facility\n\n"
        f"Your original upload has been retained. You only need to reupload the affected document."
    )


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


def _msg_deadline_exceeded(
    claim_id: str,
    claim_category: str,
    treatment_date: date,
    submitted_on: date,
    deadline_days: int,
    days_overdue: int,
) -> str:
    deadline_date = treatment_date + timedelta(days=deadline_days)
    return (
        f"Claim cannot be processed \u2014 Submission deadline passed.\n\n"
        f"Your {claim_category} claim (Claim ID: {claim_id}) was submitted outside the allowed window.\n\n"
        f"Treatment date:    {treatment_date.isoformat()}\n"
        f"Submission date:   {submitted_on.isoformat()}\n"
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


def _detailed_missing_doc_message(
    doc_type: Any,
    claim_category: str,
    claim_id: str,
    member_name: str,
) -> str:
    dt = str(doc_type).upper()
    category_label = _readable_category(claim_category)
    if dt == "PRESCRIPTION":
        return _msg_missing_prescription(claim_id, category_label, member_name)
    if dt == "HOSPITAL_BILL":
        return _msg_missing_hospital_bill(claim_id, category_label)
    if dt in ("LAB_REPORT", "DIAGNOSTIC_REPORT"):
        return _msg_missing_lab_report(claim_id)
    if dt == "PHARMACY_BILL":
        return _msg_missing_pharmacy_bill(claim_id)
    missing_label = _readable_doc_type(dt)
    return (
        f"Claim cannot proceed \u2014 {missing_label} missing.\n\n"
        f"Your {category_label} claim (Claim ID: {claim_id}) requires a {missing_label} "
        f"but none was found in your submission.\n\n"
        f"Please upload the required {missing_label} and resubmit."
    )


def _msg_multiple_missing(missing: list, claim_id: str, claim_category: str) -> str:
    category_label = _readable_category(claim_category)
    missing_labels = _join_doc_types(missing)
    return (
        f"Claim cannot proceed \u2014 Multiple required documents missing.\n\n"
        f"Your {category_label} claim (Claim ID: {claim_id}) is missing the following "
        f"required documents: {missing_labels}.\n\n"
        f"Please upload all required documents and resubmit."
    )
