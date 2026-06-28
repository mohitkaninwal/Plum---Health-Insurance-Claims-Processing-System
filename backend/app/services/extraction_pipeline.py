from __future__ import annotations

import base64
import io
import json
from datetime import datetime
import re
from typing import Any, NotRequired, TypedDict

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.models import (
    ClaimSubmission,
    ComponentFailure,
    DocumentClassification,
    DocumentQuality,
    DocumentType,
    ExtractedDocumentData,
    MemberActionRequired,
    TraceEvent,
    TraceLevel,
    UploadedDocument,
)
from app.services.document_intake import classify_document

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - dependency import guard
    PdfReader = None


class ExtractionPipelineResult(BaseModel):
    submission: ClaimSubmission
    extracted_documents: list[ExtractedDocumentData] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)
    component_failures: list[ComponentFailure] = Field(default_factory=list)
    member_action_required: MemberActionRequired | None = None
    confidence_impact: float = 0


class _ExtractionState(TypedDict):
    submission: ClaimSubmission
    classifications: NotRequired[list[DocumentClassification]]
    extracted_documents: NotRequired[list[ExtractedDocumentData]]
    trace: NotRequired[list[TraceEvent]]
    component_failures: NotRequired[list[ComponentFailure]]
    member_action_required: NotRequired[MemberActionRequired | None]
    confidence_impact: NotRequired[float]


class _LLMExtractionPayload(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)


def run_extraction_pipeline(submission: ClaimSubmission) -> ExtractionPipelineResult:
    preparsed = _extraction_from_preparsed_content(submission)
    if preparsed is not None:
        return preparsed

    graph = _build_graph()
    state = graph.invoke(
        {
            "submission": submission,
            "trace": [],
            "component_failures": [],
            "extracted_documents": [],
            "member_action_required": None,
            "confidence_impact": 0.0,
        }
    )
    return ExtractionPipelineResult.model_validate(state)


def _extraction_from_preparsed_content(submission: ClaimSubmission) -> ExtractionPipelineResult | None:
    """
    Fast path for claims submitted via the frontend upload flow.
    If every document already has content.parsed_fields from /claims/parse/upload,
    build the ExtractionPipelineResult directly without re-running LangGraph.
    """
    if not submission.documents:
        return None
    if not all(
        isinstance((doc.content or {}).get("parsed_fields"), dict)
        for doc in submission.documents
    ):
        return None

    extracted: list[ExtractedDocumentData] = []
    low_quality: list[str] = []
    confidence_impact = 0.0

    for doc in submission.documents:
        content = doc.content or {}
        parsed_fields = dict(content.get("parsed_fields") or {})
        classification = classify_document(doc).classification
        doc_type = classification.document_type

        if doc.quality == DocumentQuality.LOW:
            low_quality.append(doc.file_id)

        parsed_confidence = content.get("parsed_confidence")
        parsed_missing = list(content.get("parsed_missing_fields") or [])
        parsed_warnings = list(content.get("parsed_warnings") or [])

        confidence = (
            float(parsed_confidence)
            if isinstance(parsed_confidence, (int, float))
            else (0.92 if not parsed_missing else max(0.65, 0.9 - 0.08 * len(parsed_missing)))
        )

        if parsed_missing:
            confidence_impact -= min(0.08, 0.02 * len(parsed_missing))

        extracted.append(
            ExtractedDocumentData(
                file_id=doc.file_id,
                document_type=doc_type,
                quality=_quality_from_confidence(confidence, parsed_missing),
                fields=parsed_fields,
                missing_fields=parsed_missing,
                confidence=confidence,
                warnings=parsed_warnings,
            )
        )

    if low_quality:
        confidence_impact -= 0.03

    trace = [
        TraceEvent(
            component="DocumentVerifierAgent",
            message="Documents verified; using pre-parsed content from upload step.",
            input_summary={"document_count": len(submission.documents)},
            output_summary={
                "file_ids": [d.file_id for d in submission.documents],
                "low_or_unknown_quality_file_ids": low_quality,
            },
            confidence_impact=-0.03 if low_quality else 0,
        ),
        TraceEvent(
            component="VisionExtractionAgent",
            message="Re-extraction skipped — fields already parsed during document upload.",
            output_summary={
                "documents": [
                    {
                        "file_id": item.file_id,
                        "document_type": item.document_type,
                        "field_names": sorted(item.fields),
                        "missing_fields": item.missing_fields,
                        "confidence": item.confidence,
                    }
                    for item in extracted
                ]
            },
            confidence_impact=confidence_impact,
        ),
    ]

    member_action_required: MemberActionRequired | None = None
    unreadable = [data for data in extracted if data.quality == DocumentQuality.UNREADABLE]
    if unreadable:
        affected_ids = [data.file_id for data in unreadable]
        doc_by_id = {doc.file_id: doc for doc in submission.documents}
        affected_names = [doc_by_id[fid].file_name or fid for fid in affected_ids if fid in doc_by_id]
        member_action_required = MemberActionRequired(
            code="UNREADABLE_DOCUMENT",
            message=(
                f"The following document(s) could not be read or extracted: "
                f"{', '.join(affected_names)}. "
                "Please re-upload clearer images or provide a higher quality PDF."
            ),
            affected_file_ids=affected_ids,
        )

    return ExtractionPipelineResult(
        submission=submission,
        extracted_documents=extracted,
        trace=trace,
        component_failures=[],
        member_action_required=member_action_required,
        confidence_impact=confidence_impact,
    )


def _build_graph() -> Any:
    from langgraph.graph import END, StateGraph

    graph = StateGraph(_ExtractionState)
    graph.add_node("document_verifier", _document_verifier_agent)
    graph.add_node("vision_extraction", _vision_extraction_agent)
    graph.add_node("structured_normalization", _structured_normalization_agent)
    graph.add_node("patient_consistency", _patient_consistency_agent)
    graph.set_entry_point("document_verifier")
    graph.add_edge("document_verifier", "vision_extraction")
    graph.add_edge("vision_extraction", "structured_normalization")
    graph.add_edge("structured_normalization", "patient_consistency")
    graph.add_edge("patient_consistency", END)
    return graph.compile()


def _document_verifier_agent(state: _ExtractionState) -> _ExtractionState:
    submission = state["submission"]
    classifications = [classify_document(document).classification for document in submission.documents]
    low_quality = [
        document.file_id
        for document in submission.documents
        if document.quality == DocumentQuality.LOW
    ]
    state["classifications"] = classifications
    state["trace"] = [
        *state.get("trace", []),
        TraceEvent(
            component="DocumentVerifierAgent",
            message="Extraction inputs verified after intake validation.",
            input_summary={"document_count": len(submission.documents)},
            output_summary={
                "file_ids": [document.file_id for document in submission.documents],
                "low_or_unknown_quality_file_ids": low_quality,
            },
            confidence_impact=-0.03 if low_quality else 0,
        ),
    ]
    state["confidence_impact"] = state.get("confidence_impact", 0.0) + (-0.03 if low_quality else 0)
    return state


def _vision_extraction_agent(state: _ExtractionState) -> _ExtractionState:
    submission = state["submission"]
    classifications = state.get("classifications", [])
    extracted: list[ExtractedDocumentData] = []
    failures = list(state.get("component_failures", []))
    initial_confidence_impact = state.get("confidence_impact", 0.0)
    confidence_impact = initial_confidence_impact

    for document, classification in zip(submission.documents, classifications, strict=False):
        data = _extract_from_fixture_content(document, classification.document_type)
        if data is None:
            data = _extract_from_uploaded_text(document, classification.document_type)
        if data is None:
            data, failure = _extract_with_groq(document, classification.document_type)
            if failure is not None:
                failures.append(failure)
                confidence_impact -= 0.08
        extracted.append(data)
        if data.missing_fields:
            confidence_impact -= min(0.08, 0.02 * len(data.missing_fields))

    state["extracted_documents"] = extracted
    state["component_failures"] = failures
    state["confidence_impact"] = confidence_impact

    unreadable = [data for data in extracted if data.quality == DocumentQuality.UNREADABLE]
    if unreadable and not state.get("member_action_required"):
        affected_ids = [data.file_id for data in unreadable]
        doc_by_id = {doc.file_id: doc for doc in submission.documents}
        affected_names = [doc_by_id[fid].file_name or fid for fid in affected_ids if fid in doc_by_id]
        state["member_action_required"] = MemberActionRequired(
            code="UNREADABLE_DOCUMENT",
            message=(
                f"The following document(s) could not be read or extracted: "
                f"{', '.join(affected_names)}. "
                "Please re-upload clearer images or provide a higher quality PDF."
            ),
            affected_file_ids=affected_ids,
        )

    state["trace"] = [
        *state.get("trace", []),
        TraceEvent(
            component="VisionExtractionAgent",
            message="Document fields extracted and Pydantic-validated.",
            output_summary={
                "documents": [
                    {
                        "file_id": item.file_id,
                        "document_type": item.document_type,
                        "field_names": sorted(item.fields),
                        "missing_fields": item.missing_fields,
                        "confidence": item.confidence,
                    }
                    for item in extracted
                ]
            },
            confidence_impact=confidence_impact - initial_confidence_impact,
        ),
    ]
    return state


def _structured_normalization_agent(state: _ExtractionState) -> _ExtractionState:
    normalized = [_normalize_extracted_data(item) for item in state.get("extracted_documents", [])]
    state["extracted_documents"] = normalized
    state["submission"] = _submission_with_extracted_content(state["submission"], normalized)
    state["trace"] = [
        *state.get("trace", []),
        TraceEvent(
            component="StructuredNormalizationAgent",
            message="Extracted fields normalized for deterministic rule checks.",
            output_summary={
                "documents": [
                    {
                        "file_id": item.file_id,
                        "normalized_fields": sorted(item.fields),
                        "warnings": item.warnings,
                    }
                    for item in normalized
                ]
            },
        ),
    ]
    return state


def _patient_consistency_agent(state: _ExtractionState) -> _ExtractionState:
    extracted = state.get("extracted_documents", [])
    names_by_key: dict[str, list[str]] = {}
    display_names: dict[str, str] = {}

    for item in extracted:
        raw_name = item.fields.get("patient_name")
        if not raw_name:
            continue
        name = str(raw_name).strip()
        key = _name_key(name)
        if not key:
            continue
        names_by_key.setdefault(key, []).append(item.file_id)
        display_names.setdefault(key, name)

    if len(names_by_key) > 1:
        names = [display_names[key] for key in sorted(names_by_key)]
        affected_file_ids = [file_id for key in sorted(names_by_key) for file_id in names_by_key[key]]
        message = (
            "Extracted patient names are inconsistent across documents: "
            f"{', '.join(names)}. Please upload documents for the same patient."
        )
        state["member_action_required"] = MemberActionRequired(
            code="PATIENT_MISMATCH",
            message=message,
            affected_file_ids=affected_file_ids,
        )
        state["trace"] = [
            *state.get("trace", []),
            TraceEvent(
                component="PatientConsistencyAgent",
                level=TraceLevel.WARNING,
                message=message,
                output_summary={"patient_names": names, "affected_file_ids": affected_file_ids},
                confidence_impact=-0.25,
            ),
        ]
        state["confidence_impact"] = state.get("confidence_impact", 0.0) - 0.25
        return state

    state["trace"] = [
        *state.get("trace", []),
        TraceEvent(
            component="PatientConsistencyAgent",
            message="Extracted patient identity fields are consistent or unavailable.",
            output_summary={"patient_names": [display_names[key] for key in sorted(display_names)]},
        ),
    ]
    return state


def _extract_from_fixture_content(
    document: UploadedDocument, document_type: DocumentType
) -> ExtractedDocumentData | None:
    content = document.content or {}
    if not content or set(content) == {"upload"}:
        return None

    fields = content.get("parsed_fields") if isinstance(content.get("parsed_fields"), dict) else content
    normalized_fields = _normalize_fields(dict(fields))
    if not normalized_fields:
        return None

    missing_fields = _missing_fields(document_type, normalized_fields)
    confidence = 0.92 if not missing_fields else max(0.65, 0.9 - 0.08 * len(missing_fields))
    warnings = [f"Missing {field}." for field in missing_fields]
    return ExtractedDocumentData(
        file_id=document.file_id,
        document_type=document_type,
        quality=_quality_from_confidence(confidence, missing_fields),
        fields=normalized_fields,
        missing_fields=missing_fields,
        confidence=confidence,
        warnings=warnings,
    )


def _extract_from_uploaded_text(
    document: UploadedDocument, document_type: DocumentType
) -> ExtractedDocumentData | None:
    upload = (document.content or {}).get("upload", {})
    content_base64 = upload.get("base64")
    content_type = upload.get("content_type") or ""
    if not content_base64:
        return None

    try:
        content = base64.b64decode(content_base64)
    except Exception:
        return None

    text = _uploaded_text(content, content_type, document.file_name or "")
    if not text or not text.strip():
        return None

    parsed_fields = _parse_document_text(text, document_type)
    if not parsed_fields:
        return None

    missing_fields = _missing_fields(document_type, parsed_fields)
    if settings.groq_api_key and missing_fields:
        try:
            payload = _request_groq_text_extraction(document_type, text)
            refined_fields = _normalize_fields(payload.fields)
            if refined_fields:
                parsed_fields = refined_fields
                missing_fields = payload.missing_fields or _missing_fields(document_type, parsed_fields)
                return ExtractedDocumentData(
                    file_id=document.file_id,
                    document_type=document_type,
                    quality=_quality_from_confidence(payload.confidence, missing_fields),
                    fields=parsed_fields,
                    missing_fields=missing_fields,
                    confidence=payload.confidence,
                    warnings=payload.warnings,
                )
        except Exception:
            pass

    confidence = _parsed_text_confidence(document_type, parsed_fields, missing_fields)
    warnings = [f"Missing {field}." for field in missing_fields]
    return ExtractedDocumentData(
        file_id=document.file_id,
        document_type=document_type,
        quality=_quality_from_confidence(confidence, missing_fields),
        fields=parsed_fields,
        missing_fields=missing_fields,
        confidence=confidence,
        warnings=warnings,
    )


def _extract_with_groq(
    document: UploadedDocument, document_type: DocumentType
) -> tuple[ExtractedDocumentData, ComponentFailure | None]:
    upload = (document.content or {}).get("upload", {})
    content_base64 = upload.get("base64")
    content_type = upload.get("content_type")

    if not settings.groq_api_key or not content_base64 or not content_type:
        return _empty_extraction(document, document_type, has_upload_content=bool(content_base64)), ComponentFailure(
            component="VisionExtractionAgent",
            message=(
                f"No OCR payload is available for {document.file_id}; continued with claim-level "
                "amount and document classification evidence."
            ),
        )

    try:
        payload = _request_groq_extraction(document_type, content_base64, content_type)
        return ExtractedDocumentData(
            file_id=document.file_id,
            document_type=document_type,
            quality=_quality_from_confidence(payload.confidence, payload.missing_fields),
            fields=payload.fields,
            missing_fields=payload.missing_fields,
            confidence=payload.confidence,
            warnings=payload.warnings,
        ), None
    except Exception as exc:
        return _empty_extraction(document, document_type, has_upload_content=True), ComponentFailure(
            component="VisionExtractionAgent",
            message=f"Groq extraction failed for {document.file_id}: {exc}",
        )


def _request_groq_extraction(
    document_type: DocumentType, content_base64: str, content_type: str
) -> _LLMExtractionPayload:
    from groq import Groq

    client = Groq(api_key=settings.groq_api_key)
    prompt = (
        "Extract structured health-insurance claim fields from this document. Return only JSON "
        "matching this schema: fields object, missing_fields string array, confidence number "
        "between 0 and 1, warnings string array. Normalize patient_name, diagnosis, hospital_name, "
        "total, test_name, line_items, invoice_date, and pre_authorization_number when present. "
        "invoice_date must be ISO YYYY-MM-DD. For Indian documents, interpret numeric dates as "
        "DD/MM/YYYY unless impossible, so 03/11/2024 means 2024-11-03. For pharmacy bills, "
        "line_items must include the medicine description and the row Amount total, not zero, "
        "quantity, or MRP. Use NET AMOUNT or GRAND TOTAL for total when present. "
        f"The classified document_type is {document_type}."
    )
    response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{content_type};base64,{content_base64}"},
                    },
                ],
            }
        ],
        temperature=0,
    )
    raw = response.choices[0].message.content or "{}"
    try:
        return _parse_llm_extraction_payload(raw)
    except (ValidationError, ValueError) as original_exc:
        repair = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Repair this into valid JSON only with keys fields, missing_fields, "
                        f"confidence, warnings: {raw}"
                    ),
                }
            ],
            temperature=0,
        )
        try:
            return _parse_llm_extraction_payload(repair.choices[0].message.content or "{}")
        except (ValidationError, ValueError) as repair_exc:
            raise repair_exc from original_exc


def _request_groq_text_extraction(document_type: DocumentType, text: str) -> _LLMExtractionPayload:
    from groq import Groq

    client = Groq(api_key=settings.groq_api_key)
    prompt = (
        "Extract structured health-insurance claim fields from this OCR text excerpt. Return only "
        "JSON matching this schema: fields object, missing_fields string array, confidence number "
        "between 0 and 1, warnings string array. Normalize patient_name, diagnosis, hospital_name, "
        "total, test_name, line_items, invoice_date, and pre_authorization_number when present. "
        "invoice_date must be ISO YYYY-MM-DD. For Indian documents, interpret numeric dates as "
        "DD/MM/YYYY unless impossible, so 03/11/2024 means 2024-11-03. For pharmacy bills, "
        "line_items must include the medicine description and the row Amount total, not zero, "
        "quantity, or MRP. Use NET AMOUNT or GRAND TOTAL for total when present. "
        f"The classified document_type is {document_type}. OCR text excerpt:\n{text[:12000]}"
    )
    response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw = response.choices[0].message.content or "{}"
    try:
        return _parse_llm_extraction_payload(raw)
    except (ValidationError, ValueError) as original_exc:
        repair = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Repair this into valid JSON only with keys fields, missing_fields, "
                        f"confidence, warnings: {raw}"
                    ),
                }
            ],
            temperature=0,
        )
        try:
            return _parse_llm_extraction_payload(repair.choices[0].message.content or "{}")
        except (ValidationError, ValueError) as repair_exc:
            raise repair_exc from original_exc


def _parse_llm_extraction_payload(raw: str) -> _LLMExtractionPayload:
    last_error: ValidationError | None = None
    for candidate in _json_object_candidates(raw):
        try:
            return _LLMExtractionPayload.model_validate(candidate)
        except ValidationError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ValueError("No JSON object was found in the LLM extraction response.")


def _json_object_candidates(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    candidates: list[dict[str, Any]] = []

    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            candidates.append(loaded)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            loaded, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            candidates.append(loaded)

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = json.dumps(candidate, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _empty_extraction(
    document: UploadedDocument,
    document_type: DocumentType,
    has_upload_content: bool = False,
) -> ExtractedDocumentData:
    fields: dict[str, Any] = {}
    if document.patient_name_on_doc:
        fields["patient_name"] = document.patient_name_on_doc
    missing_fields = _missing_fields(document_type, fields)
    confidence = 0.58 if fields else 0.5
    # Mark as UNREADABLE only when actual binary content was uploaded but could not be extracted.
    # When there was no upload content at all (e.g. fixture documents), stay LOW.
    quality = DocumentQuality.UNREADABLE if has_upload_content and not fields else DocumentQuality.LOW
    return ExtractedDocumentData(
        file_id=document.file_id,
        document_type=document_type,
        quality=quality,
        fields=fields,
        missing_fields=missing_fields,
        confidence=confidence,
        warnings=["LLM/OCR extraction unavailable; preserved available local fields."],
    )


def _quality_from_confidence(confidence: float, missing_fields: list[str]) -> DocumentQuality:
    if confidence >= 0.8 and not missing_fields:
        return DocumentQuality.GOOD
    if confidence >= 0.5:
        return DocumentQuality.LOW
    return DocumentQuality.UNREADABLE


def _uploaded_text(content: bytes, content_type: str, file_name: str) -> str | None:
    content_type = content_type.lower()
    file_name = file_name.lower()

    if content_type.startswith("text/") or file_name.endswith(".txt"):
        return content.decode("utf-8", errors="ignore")

    if content_type.startswith("application/pdf") or file_name.endswith(".pdf"):
        if PdfReader is None:
            return None
        try:
            reader = PdfReader(io.BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception:
            return None
        text = "\n".join(page.strip() for page in pages if page and page.strip())
        return text or None

    return None


def _parse_document_text(text: str, document_type: DocumentType) -> dict[str, Any]:
    lines = [_normalize_whitespace(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    normalized_text = "\n".join(lines)
    fields: dict[str, Any] = {}

    patient_name = _extract_first_match(
        normalized_text,
        [
            r"\bpatient(?:\s+name)?\b\s*[:\-]\s*(.+?)(?=\s{2,}|\bdate\b|\bage\b|\bgender\b|\bsex\b|$)",
            r"\bname\b\s*[:\-]\s*(.+?)(?=\s{2,}|\bdate\b|\bage\b|\bgender\b|\bsex\b|$)",
        ],
    )
    if patient_name:
        fields["patient_name"] = patient_name

    doctor_name = _extract_first_match(
        normalized_text,
        [
            r"\b(?:ref(?:erring)?\s*)?(?:doctor|dr\.?)\b\s*[:\-]\s*(.+?)(?=\s{2,}|$)",
            r"(?:^|\n)\s*(Dr\.[^\n,]+)",
        ],
    )
    if doctor_name:
        fields["doctor_name"] = doctor_name

    hospital_name = _extract_hospital_name(lines)
    if hospital_name:
        fields["hospital_name"] = hospital_name

    diagnosis = _extract_first_match(
        normalized_text,
        [
            r"\b(?:primary\s+)?diagnosis\b\s*[:\-]\s*(.+?)(?=\s{2,}|$)",
            r"\bimpression\b\s*[:\-]\s*(.+?)(?=\s{2,}|$)",
            r"\bprovisional\s+diagnosis\b\s*[:\-]\s*(.+?)(?=\s{2,}|$)",
        ],
    )
    if diagnosis:
        fields["diagnosis"] = diagnosis

    invoice_date = _extract_first_match(
        normalized_text,
        [
            r"\b(?:invoice|bill|report|sample)\s+date\b\s*[:\-]\s*([0-9A-Za-z/\-]+)",
            r"\bdate\b\s*[:\-]\s*([0-9A-Za-z/\-]+)",
        ],
    )
    if invoice_date:
        normalized_invoice_date = _normalize_date_value(invoice_date)
        fields["invoice_date"] = normalized_invoice_date or invoice_date

    bill_like_document = document_type in {
        DocumentType.HOSPITAL_BILL,
        DocumentType.PHARMACY_BILL,
        DocumentType.DENTAL_REPORT,
    }

    total = None
    if bill_like_document:
        total = _extract_amount(
            lines,
            [
                r"\b(?:net\s+amount|grand\s+total|total\s+amount|amount\s+due|bill\s+amount|invoice\s+total)\b",
                r"\bsubtotal\b",
            ],
        )
        if total is not None:
            fields["total"] = total

    tests = _extract_section_values(lines, ["investigations", "test name", "tests ordered", "tests"])
    if tests:
        fields["test_name"] = tests[0] if len(tests) == 1 else tests
    elif document_type in {DocumentType.LAB_REPORT, DocumentType.DIAGNOSTIC_REPORT}:
        parsed_tests = _parse_table_descriptions(lines)
        if parsed_tests:
            fields["test_name"] = parsed_tests[0] if len(parsed_tests) == 1 else parsed_tests

    if bill_like_document:
        line_items = _parse_line_items(lines)
        if line_items:
            fields["line_items"] = line_items
            if total is None:
                numeric_amounts = [
                    item["amount"]
                    for item in line_items
                    if isinstance(item.get("amount"), (int, float))
                ]
                if numeric_amounts:
                    fields["total"] = float(sum(float(amount) for amount in numeric_amounts))

    return fields


def _extract_first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if not match:
            continue
        value = _clean_extracted_value(match.group(1))
        if value:
            return value
    return None


def _extract_hospital_name(lines: list[str]) -> str | None:
    candidates: list[tuple[int, str]] = []
    keywords = ("hospital", "clinic", "centre", "center", "diagnostic", "pharmacy", "lab", "laboratory")
    for index, line in enumerate(lines[:10]):
        lowered = line.lower()
        if not any(keyword in lowered for keyword in keywords):
            continue
        if re.search(r"\b(patient|bill|invoice|report|date|total|gstin)\b", lowered):
            continue
        score = 0
        if line == line.upper():
            score += 2
        if index == 0:
            score += 1
        if len(line) <= 80:
            score += 1
        candidates.append((score, line))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _extract_amount(lines: list[str], labels: list[str]) -> float | None:
    for line in reversed(lines):
        lowered = line.lower()
        if not any(re.search(label, line, flags=re.IGNORECASE) for label in labels):
            continue
        numeric_candidates = _amount_candidates(line)
        if numeric_candidates:
            return float(numeric_candidates[-1])
    return None


def _extract_section_values(lines: list[str], headings: list[str]) -> list[str]:
    values: list[str] = []
    capture = False
    heading_patterns = [heading.lower() for heading in headings]
    for line in lines:
        lowered = line.lower()
        if any(heading in lowered for heading in heading_patterns):
            after = re.split(r"[:\-]", line, maxsplit=1)
            if len(after) > 1 and after[1].strip():
                values.extend(_split_list_values(after[1].strip()))
            capture = True
            continue
        if capture:
            if re.search(r"\b(?:remarks?|summary|findings?|subtotal|total|amount)\b", lowered):
                break
            if not line:
                break
            values.extend(_split_list_values(line))
    return _dedupe_preserve_order(values)


def _parse_table_descriptions(lines: list[str]) -> list[str]:
    descriptions: list[str] = []
    for line in lines:
        if re.search(r"\b(?:patient|bill|invoice|date|report|sample|subtotal|total|remarks?)\b", line, flags=re.IGNORECASE):
            continue
        chunks = re.split(r"\s{2,}", line.strip())
        if len(chunks) < 2:
            continue
        if not re.fullmatch(r"(?:₹|INR|Rs\.?)?\s*[\d,]+(?:\.\d{1,2})?", chunks[-1], flags=re.IGNORECASE):
            continue
        description = _clean_extracted_value(chunks[0])
        if description:
            descriptions.append(description)
    return _dedupe_preserve_order(descriptions)


def _parse_line_items(lines: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in lines:
        lowered = line.lower()
        if re.search(r"\b(?:patient|bill|invoice|date|report|sample|subtotal|total|remarks?|gstin|age|gender|sex)\b", lowered):
            continue
        numeric_candidates = _amount_candidates(line)
        if len(numeric_candidates) < 2:
            continue
        has_monetary_marker = bool(
            re.search(r"(?:₹|inr|rs\.?)", line, flags=re.IGNORECASE)
            or re.search(r"\b(?:amount|fee|charges?|charge|total|subtotal)\b", lowered)
        )
        if not has_monetary_marker and numeric_candidates[-1] != numeric_candidates[-2]:
            continue
        suffix_amount = numeric_candidates[-1]
        description = _clean_extracted_value(
            re.sub(r"(?:₹|inr|rs\.?)?\s*[\d,]+(?:\.\d{1,2})?\s*$", "", line, flags=re.IGNORECASE)
        )
        if not description:
            continue
        items.append({"description": description, "amount": suffix_amount})
    return items


def _split_list_values(raw: str) -> list[str]:
    parts = [part.strip() for part in re.split(r",|/|;|\band\b", raw, flags=re.IGNORECASE) if part.strip()]
    return [_clean_extracted_value(part) for part in parts if _clean_extracted_value(part)]


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_date_value(value: str) -> str | None:
    cleaned = _normalize_whitespace(value)
    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%d %b %Y",
        "%d %B %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue

    match = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", cleaned)
    if match:
        year, month, day = map(int, match.groups())
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return None

    match = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", cleaned)
    if match:
        day, month, year = map(int, match.groups())
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return None

    return None


def _amount_candidates(value: str) -> list[float]:
    candidates: list[float] = []
    for match in re.finditer(r"(?:₹|inr|rs\.?)?\s*([\d,]+(?:\.\d{1,2})?)", value, flags=re.IGNORECASE):
        raw_value = match.group(1)
        try:
            candidates.append(float(raw_value.replace(",", "").strip()))
        except ValueError:
            continue
    return candidates


def _clean_extracted_value(value: str) -> str:
    cleaned = _normalize_whitespace(value)
    cleaned = re.sub(r"^[\s:,-]+|[\s:,-]+$", "", cleaned)
    return cleaned


def _parsed_text_confidence(
    document_type: DocumentType, fields: dict[str, Any], missing_fields: list[str]
) -> float:
    required = len(_missing_fields(document_type, fields)) + len(fields)
    base = 0.88 if required >= 3 else 0.76
    penalty = min(0.22, 0.08 * len(missing_fields))
    return max(0.55, base - penalty)


def _normalize_extracted_data(data: ExtractedDocumentData) -> ExtractedDocumentData:
    fields = _normalize_fields(data.fields)
    missing_fields = [field for field in data.missing_fields if field not in fields]
    warnings = list(data.warnings)
    if missing_fields and not any("Missing" in warning for warning in warnings):
        warnings.extend(f"Missing {field}." for field in missing_fields)
    return data.model_copy(update={"fields": fields, "missing_fields": missing_fields, "warnings": warnings})


def _normalize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "patient": "patient_name",
        "patientName": "patient_name",
        "name": "patient_name",
        "doctor_diagnosis": "diagnosis",
        "amount": "total",
        "bill_amount": "total",
        "invoice_total": "total",
        "provider": "hospital_name",
    }
    normalized: dict[str, Any] = {}
    for raw_key, value in fields.items():
        key = aliases.get(str(raw_key), _snake_case(str(raw_key)))
        if key == "document_type":
            continue
        if key == "patient_name" and value is not None:
            normalized[key] = re.sub(r"\s+", " ", str(value)).strip()
        elif key in {"invoice_date", "treatment_date"} and value is not None:
            normalized[key] = _normalize_date_value(str(value)) or str(value).strip()
        elif key in {"total", "amount"} and value is not None:
            normalized["total"] = _number_or_original(value)
        elif key == "line_items" and isinstance(value, list):
            normalized[key] = [_normalize_line_item(item) for item in value if isinstance(item, dict)]
        else:
            normalized[key] = value
    return normalized


def _normalize_line_item(item: dict[str, Any]) -> dict[str, Any]:
    description = (
        item.get("description")
        or item.get("medicine_name")
        or item.get("medicine")
        or item.get("brand_name")
        or item.get("item_name")
        or item.get("test_name")
        or item.get("procedure")
        or "Line item"
    )
    amount = item.get("amount") or item.get("total") or item.get("bill_amount") or 0
    return {"description": str(description), "amount": _number_or_original(amount)}


def _number_or_original(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", "").replace("INR", "").strip())
    except ValueError:
        return value


def _missing_fields(document_type: DocumentType, fields: dict[str, Any]) -> list[str]:
    required_by_type = {
        DocumentType.PRESCRIPTION: ["patient_name", "diagnosis"],
        DocumentType.HOSPITAL_BILL: ["patient_name", "total"],
        DocumentType.PHARMACY_BILL: ["patient_name", "total"],
        DocumentType.LAB_REPORT: ["patient_name", "test_name"],
        DocumentType.DIAGNOSTIC_REPORT: ["patient_name", "test_name"],
        DocumentType.DISCHARGE_SUMMARY: ["patient_name", "diagnosis"],
        DocumentType.DENTAL_REPORT: ["patient_name", "diagnosis"],
    }
    normalized_keys = set(_normalize_fields(fields))
    return [field for field in required_by_type.get(document_type, []) if field not in normalized_keys]


def _submission_with_extracted_content(
    submission: ClaimSubmission, extracted_documents: list[ExtractedDocumentData]
) -> ClaimSubmission:
    extracted_by_file_id = {item.file_id: item for item in extracted_documents}
    documents: list[UploadedDocument] = []
    for document in submission.documents:
        extracted = extracted_by_file_id.get(document.file_id)
        if extracted is None:
            documents.append(document)
            continue
        content = dict(document.content or {})
        for key, value in extracted.fields.items():
            content.setdefault(key, value)
        documents.append(document.model_copy(update={"content": content}))
    return submission.model_copy(update={"documents": documents})


def _snake_case(value: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()


def _name_key(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()
