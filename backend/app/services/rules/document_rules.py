"""Document rules: D01–D03 — document presence, type, and readability validation."""
from __future__ import annotations

import re
from datetime import date
from typing import Any
from uuid import uuid4

from app.models import (
    ClaimResponse,
    ClaimStatus,
    DocumentQuality,
    DocumentType,
    MemberActionRequired,
    PolicyEvidence,
    TraceEvent,
    TraceLevel,
    ClaimSubmission,
)
from app.models.policy import PolicyTerms
from app.services.document_intake import classify_document
from app.services.rules.gate_rules import (
    member_name as _member_name,
    member_dependents as _member_dependents,
    _msg_patient_mismatch,
    _name_key,
    _readable_category,
)

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


# ── Public rule function ──────────────────────────────────────────────────────


def validate_documents(
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
            f"could not be classified as a supported document type."
        )
        reason = short_msg + "\n\n" + detail
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
            reason=reason,
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
        member_name_str = _member_name(submission, policy)
        uploaded_type_names = " and ".join(str(t) for t in uploaded_types) if uploaded_types else "no recognised"
        if len(missing) == 1:
            detail = _detailed_missing_doc_message(missing[0], submission.claim_category, val_claim_id, member_name_str)
            short_msg = (
                f"A {str(missing[0])} document is required for {str(submission.claim_category)} claims, "
                f"but only {uploaded_type_names} documents were uploaded."
            )
        else:
            detail = _msg_multiple_missing(missing, val_claim_id, submission.claim_category)
            short_msg = (
                f"{_join_doc_types(missing)} are required for {category_label} claims "
                f"but were not found among your uploads."
            )
        reason = short_msg + "\n\n" + detail
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
            reason=reason,
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

    # ── Temporal sanity check (soft warning, not a hard stop) ────────────────
    # If any document's invoice_date is more than 30 days *before* the claimed
    # treatment_date it is likely a stale or mis-scanned document.  We do not
    # reject the claim — bills and lab reports can carry earlier dates — but we
    # surface the discrepancy in the trace so reviewers are aware.
    date_warnings = _invoice_date_warnings(submission)
    if date_warnings:
        trace.append(
            TraceEvent(
                component="DocumentVerifierAgent",
                level=TraceLevel.WARNING,
                message="One or more document dates are more than 30 days before the treatment date.",
                output_summary={"date_discrepancies": date_warnings},
                checks_performed=["invoice_date_vs_treatment_date"],
                warnings=date_warnings,
            )
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
                "invoice_date_vs_treatment_date",
            ],
            evidence_ids=[item.evidence_id for item in evidence if item.rule_category == "document_requirements"],
        )
    )
    return None


# ── Private helpers ───────────────────────────────────────────────────────────


def _readable_doc_type(doc_type: str) -> str:
    return _DOC_TYPE_LABELS.get(str(doc_type).upper(), str(doc_type).replace("_", " ").title())


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


def _invoice_date_warnings(submission: ClaimSubmission) -> list[str]:
    """Return a warning string for each document whose invoice_date is more
    than 30 days before the treatment date.  Documents with no invoice_date or
    an unparseable date are silently skipped.
    """
    warnings: list[str] = []
    treatment = submission.treatment_date
    for doc in submission.documents:
        content = doc.content or {}
        raw_date = content.get("invoice_date") or content.get("parsed_fields", {}).get("invoice_date")
        if not raw_date:
            continue
        parsed: date | None = None
        if isinstance(raw_date, date) and not isinstance(raw_date, type(None)):
            parsed = raw_date
        elif isinstance(raw_date, str):
            try:
                parsed = date.fromisoformat(raw_date[:10])
            except ValueError:
                continue
        if parsed is None:
            continue
        delta = (treatment - parsed).days
        if delta > 30:
            warnings.append(
                f"Document '{doc.file_name or doc.file_id}' has invoice_date {parsed.isoformat()}, "
                f"which is {delta} days before the treatment date {treatment.isoformat()}. "
                "Please verify this document belongs to the current claim."
            )
    return warnings


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
