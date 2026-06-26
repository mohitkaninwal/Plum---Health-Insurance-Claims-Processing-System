from __future__ import annotations

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
        if document.quality in {DocumentQuality.LOW, DocumentQuality.UNKNOWN}
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

    missing_fields = _missing_fields(document_type, content)
    confidence = 0.92 if not missing_fields else max(0.65, 0.9 - 0.08 * len(missing_fields))
    warnings = [f"Missing {field}." for field in missing_fields]
    return ExtractedDocumentData(
        file_id=document.file_id,
        document_type=document_type,
        fields=dict(content),
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
        return _empty_extraction(document, document_type), ComponentFailure(
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
            fields=payload.fields,
            missing_fields=payload.missing_fields,
            confidence=payload.confidence,
            warnings=payload.warnings,
        ), None
    except Exception as exc:
        return _empty_extraction(document, document_type), ComponentFailure(
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
        return _LLMExtractionPayload.model_validate_json(raw)
    except ValidationError:
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
        return _LLMExtractionPayload.model_validate_json(repair.choices[0].message.content or "{}")


def _empty_extraction(document: UploadedDocument, document_type: DocumentType) -> ExtractedDocumentData:
    fields: dict[str, Any] = {}
    if document.patient_name_on_doc:
        fields["patient_name"] = document.patient_name_on_doc
    missing_fields = _missing_fields(document_type, fields)
    return ExtractedDocumentData(
        file_id=document.file_id,
        document_type=document_type,
        fields=fields,
        missing_fields=missing_fields,
        confidence=0.58 if fields else 0.5,
        warnings=["LLM/OCR extraction unavailable; preserved available local fields."],
    )


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
        if key == "patient_name" and value is not None:
            normalized[key] = re.sub(r"\s+", " ", str(value)).strip()
        elif key in {"total", "amount"} and value is not None:
            normalized["total"] = _number_or_original(value)
        elif key == "line_items" and isinstance(value, list):
            normalized[key] = [_normalize_line_item(item) for item in value if isinstance(item, dict)]
        else:
            normalized[key] = value
    return normalized


def _normalize_line_item(item: dict[str, Any]) -> dict[str, Any]:
    description = item.get("description") or item.get("test_name") or item.get("procedure") or "Line item"
    amount = item.get("amount") or item.get("total") or item.get("bill_amount") or 0
    return {"description": str(description), "amount": _number_or_original(amount)}


def _number_or_original(value: Any) -> Any:
    if isinstance(value, int | float):
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
