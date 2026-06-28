from __future__ import annotations

import base64
import hashlib
import json
from datetime import date
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import File, Form, UploadFile

from app.core.config import settings
from app.models import (
    ClaimCategory,
    ClaimResponse,
    ClaimSubmission,
    DocumentClassification,
    DocumentQuality,
    DocumentType,
    UploadedDocument,
)


@dataclass(frozen=True)
class IntakeClassification:
    document: UploadedDocument
    classification: DocumentClassification
    source: str


class UploadDocumentForm:
    def __init__(
        self,
        member_id: Annotated[str, Form()],
        policy_id: Annotated[str, Form()],
        claim_category: Annotated[ClaimCategory, Form()],
        treatment_date: Annotated[str, Form()],
        claimed_amount: Annotated[float, Form(gt=0)],
        files: Annotated[list[UploadFile], File(min_length=1)],
        ytd_claims_amount: Annotated[float | None, Form()] = None,
        hospital_name: Annotated[str | None, Form()] = None,
        declared_types: Annotated[str | None, Form()] = None,
        patient_names: Annotated[str | None, Form()] = None,
    ) -> None:
        self.member_id = member_id
        self.policy_id = policy_id
        self.claim_category = claim_category
        self.treatment_date = treatment_date
        self.claimed_amount = claimed_amount
        self.files = files
        self.ytd_claims_amount = ytd_claims_amount
        self.hospital_name = hospital_name
        self.declared_types = declared_types
        self.patient_names = patient_names


class ParseDocumentForm:
    def __init__(
        self,
        files: Annotated[list[UploadFile], File(min_length=1)],
        member_id: Annotated[str | None, Form()] = None,
        policy_id: Annotated[str | None, Form()] = None,
        claim_category: Annotated[ClaimCategory | None, Form()] = None,
        treatment_date: Annotated[str | None, Form()] = None,
        claimed_amount: Annotated[float | None, Form()] = None,
        ytd_claims_amount: Annotated[float | None, Form()] = None,
        hospital_name: Annotated[str | None, Form()] = None,
        declared_types: Annotated[str | None, Form()] = None,
        patient_names: Annotated[str | None, Form()] = None,
    ) -> None:
        self.member_id = member_id
        self.policy_id = policy_id
        self.claim_category = claim_category
        self.treatment_date = treatment_date
        self.claimed_amount = claimed_amount
        self.files = files
        self.ytd_claims_amount = ytd_claims_amount
        self.hospital_name = hospital_name
        self.declared_types = declared_types
        self.patient_names = patient_names


def classify_document(document: UploadedDocument) -> IntakeClassification:
    if document.actual_type is not None:
        classification = DocumentClassification(
            file_id=document.file_id,
            document_type=document.actual_type,
            confidence=1.0,
            rationale="Fixture document classified from actual_type.",
        )
        return IntakeClassification(document=document, classification=classification, source="fixture")

    if document.quality == DocumentQuality.UNREADABLE:
        classification = DocumentClassification(
            file_id=document.file_id,
            document_type=document.declared_type or DocumentType.UNKNOWN,
            confidence=0.0,
            rationale="Document was marked unreadable before classification.",
        )
        return IntakeClassification(document=document, classification=classification, source="quality")

    inferred = _infer_document_type(document.file_name or document.file_id)
    if inferred is not None:
        classification = DocumentClassification(
            file_id=document.file_id,
            document_type=inferred,
            confidence=0.74,
            rationale="Classified by backend filename/type preprocessing fallback.",
        )
        return IntakeClassification(document=document, classification=classification, source="preprocessing")

    if document.declared_type is not None:
        classification = DocumentClassification(
            file_id=document.file_id,
            document_type=document.declared_type,
            confidence=0.62,
            rationale="Used submitter-declared document type after preprocessing fallback.",
        )
        return IntakeClassification(document=document, classification=classification, source="declared")

    classification = DocumentClassification(
        file_id=document.file_id,
        document_type=DocumentType.UNKNOWN,
        confidence=0.2,
        rationale="Unable to classify document with available local signals.",
    )
    return IntakeClassification(document=document, classification=classification, source="unknown")


async def submission_from_upload_form(form: UploadDocumentForm) -> ClaimSubmission:
    declared_by_name = _document_type_map(form.declared_types)
    patient_names_by_name = _string_map(form.patient_names)
    documents: list[UploadedDocument] = []

    for index, upload in enumerate(form.files, start=1):
        content = await upload.read()
        file_name = upload.filename or f"upload_{index}"
        declared_type = declared_by_name.get(file_name) or declared_by_name.get(str(index))
        patient_name = patient_names_by_name.get(file_name) or patient_names_by_name.get(str(index))
        quality = DocumentQuality.UNREADABLE if not content else DocumentQuality.UNKNOWN
        document = UploadedDocument(
            file_id=f"UPL{index:03d}",
            file_name=file_name,
            declared_type=declared_type,
            quality=quality,
            patient_name_on_doc=patient_name,
            content={
                "upload": {
                    "content_type": upload.content_type,
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "base64": base64.b64encode(content).decode("ascii"),
                }
            },
        )
        if settings.groq_api_key and upload.content_type and upload.content_type.startswith("image/"):
            document = _classify_with_groq_vision(document, content, upload.content_type)
        documents.append(document)

    return ClaimSubmission(
        member_id=form.member_id,
        policy_id=form.policy_id,
        claim_category=form.claim_category,
        treatment_date=form.treatment_date,
        claimed_amount=form.claimed_amount,
        documents=documents,
        ytd_claims_amount=form.ytd_claims_amount,
        hospital_name=form.hospital_name,
    )


async def submission_from_parse_form(form: ParseDocumentForm) -> ClaimSubmission:
    declared_by_name = _document_type_map(form.declared_types)
    patient_names_by_name = _string_map(form.patient_names)
    documents: list[UploadedDocument] = []

    for index, upload in enumerate(form.files, start=1):
        content = await upload.read()
        file_name = upload.filename or f"upload_{index}"
        declared_type = declared_by_name.get(file_name) or declared_by_name.get(str(index))
        patient_name = patient_names_by_name.get(file_name) or patient_names_by_name.get(str(index))
        quality = DocumentQuality.UNREADABLE if not content else DocumentQuality.UNKNOWN
        document = UploadedDocument(
            file_id=f"UPL{index:03d}",
            file_name=file_name,
            declared_type=declared_type,
            quality=quality,
            patient_name_on_doc=patient_name,
            content={
                "upload": {
                    "content_type": upload.content_type,
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "base64": base64.b64encode(content).decode("ascii"),
                }
            },
        )
        if settings.groq_api_key and upload.content_type and upload.content_type.startswith("image/"):
            document = _classify_with_groq_vision(document, content, upload.content_type)
        documents.append(document)

    return ClaimSubmission(
        member_id=form.member_id or "UNKNOWN_MEMBER",
        policy_id=form.policy_id or "UNKNOWN_POLICY",
        claim_category=form.claim_category or ClaimCategory.CONSULTATION,
        treatment_date=form.treatment_date or date.today(),
        claimed_amount=form.claimed_amount or 1,
        documents=documents,
        ytd_claims_amount=form.ytd_claims_amount,
        hospital_name=form.hospital_name,
    )


def response_without_upload_payloads(response: ClaimResponse) -> ClaimResponse:
    if response.submission is None:
        return response

    documents: list[UploadedDocument] = []
    for document in response.submission.documents:
        content = dict(document.content or {})
        upload = content.get("upload")
        if isinstance(upload, dict) and "base64" in upload:
            content["upload"] = {key: value for key, value in upload.items() if key != "base64"}
        documents.append(document.model_copy(update={"content": content}))

    return response.model_copy(
        update={"submission": response.submission.model_copy(update={"documents": documents})}
    )


def _classify_with_groq_vision(
    document: UploadedDocument, content: bytes, content_type: str
) -> UploadedDocument:
    try:
        from groq import Groq

        client = Groq(api_key=settings.groq_api_key)
        encoded = base64.b64encode(content).decode("ascii")
        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Classify this insurance claim document. Return only JSON with "
                                "document_type as one of PRESCRIPTION, HOSPITAL_BILL, LAB_REPORT, "
                                "DIAGNOSTIC_REPORT, PHARMACY_BILL, DISCHARGE_SUMMARY, DENTAL_REPORT, "
                                "UNKNOWN and quality as GOOD, LOW, UNREADABLE, or UNKNOWN."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{content_type};base64,{encoded}",
                            },
                        },
                    ],
                }
            ],
            temperature=0,
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        return document.model_copy(
            update={
                "actual_type": DocumentType(payload.get("document_type", DocumentType.UNKNOWN)),
                "quality": DocumentQuality(payload.get("quality", document.quality)),
            }
        )
    except Exception:
        return document


def _infer_document_type(file_name: str) -> DocumentType | None:
    normalized = Path(file_name).stem.lower().replace("-", "_").replace(" ", "_")
    if "prescription" in normalized or "rx" in normalized:
        return DocumentType.PRESCRIPTION
    if "pharmacy" in normalized or "medicine_bill" in normalized or "drug_bill" in normalized:
        return DocumentType.PHARMACY_BILL
    if "lab" in normalized or "diagnostic_report" in normalized:
        return DocumentType.LAB_REPORT
    if "diagnostic" in normalized or "scan" in normalized:
        return DocumentType.DIAGNOSTIC_REPORT
    if "discharge" in normalized:
        return DocumentType.DISCHARGE_SUMMARY
    if "dental" in normalized:
        return DocumentType.DENTAL_REPORT
    if "bill" in normalized or "invoice" in normalized or "receipt" in normalized:
        return DocumentType.HOSPITAL_BILL
    return None


def _document_type_map(raw: str | None) -> dict[str, DocumentType]:
    values = _string_map(raw)
    parsed: dict[str, DocumentType] = {}
    for key, value in values.items():
        try:
            parsed[key] = DocumentType(value)
        except ValueError as exc:
            raise ValueError(f"Invalid document type for {key}: {value}") from exc
    return parsed


def _string_map(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("Expected a JSON object.")
    return {str(key): str(value) for key, value in loaded.items() if value is not None}
