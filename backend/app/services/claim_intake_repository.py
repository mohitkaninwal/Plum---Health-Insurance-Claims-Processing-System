from __future__ import annotations

from typing import Any

import logging

from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

from app.core.config import settings
from app.db.models import ClaimIntakeRecord, UploadedDocumentRecord
from app.db.session import SessionLocal
from app.models import ClaimResponse, ComponentFailure, TraceEvent, TraceLevel
from app.services.document_intake import classify_document


def persist_claim_intake(response: ClaimResponse) -> ClaimResponse:
    if SessionLocal is None or response.submission is None:
        return response

    db = SessionLocal()
    try:
        _replace_claim_intake(response, db)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("ClaimIntakeRepository persist failed for claim %s: %r", response.claim_id, exc)
        if settings.environment.lower() in {"local", "test"}:
            return response
        response.component_failures.append(
            ComponentFailure(
                component="ClaimIntakeRepository",
                message=f"Claim intake metadata could not be persisted: {exc}",
            )
        )
        response.trace.append(
            TraceEvent(
                component="ClaimIntakeRepository",
                level=TraceLevel.WARNING,
                message="Claim intake metadata persistence failed; processing response was still returned.",
            )
        )
    finally:
        db.close()
    return response


def _replace_claim_intake(response: ClaimResponse, db: Any) -> None:
    submission = response.submission
    if submission is None:
        return

    existing = db.get(ClaimIntakeRecord, response.claim_id)
    if existing is not None:
        db.delete(existing)
        db.flush()

    validation_status = _validation_status(response)
    record = ClaimIntakeRecord(
        claim_id=response.claim_id,
        member_id=submission.member_id,
        policy_id=submission.policy_id,
        claim_category=str(submission.claim_category),
        treatment_date=submission.treatment_date,
        claimed_amount=submission.claimed_amount,
        ytd_claims_amount=submission.ytd_claims_amount,
        hospital_name=submission.hospital_name,
        status=str(response.status),
        decision=str(response.decision.decision) if response.decision else None,
        approved_amount=response.approved_amount,
        confidence_score=response.confidence_score,
        reason=response.reason,
        validation_status=validation_status,
        member_action_code=(
            response.member_action_required.code if response.member_action_required else None
        ),
        rejection_reasons=[str(reason) for reason in response.rejection_reasons],
        trace=[event.model_dump(mode="json") for event in response.trace],
        component_failures=[failure.model_dump(mode="json") for failure in response.component_failures],
    )
    db.add(record)
    db.flush()

    for document in submission.documents:
        classification = classify_document(document)
        metadata = document.content if isinstance(document.content, dict) else {}
        upload_metadata = metadata.get("upload", {}) if isinstance(metadata.get("upload"), dict) else {}
        db.add(
            UploadedDocumentRecord(
                claim_id=response.claim_id,
                file_id=document.file_id,
                file_name=document.file_name,
                mime_type=upload_metadata.get("content_type"),
                size_bytes=upload_metadata.get("size_bytes"),
                sha256=upload_metadata.get("sha256"),
                storage_uri=upload_metadata.get("storage_uri"),
                declared_type=str(document.declared_type) if document.declared_type else None,
                classified_type=str(classification.classification.document_type),
                classification_confidence=classification.classification.confidence,
                classification_source=classification.source,
                quality=str(document.quality),
                patient_name_on_doc=document.patient_name_on_doc,
                validation_status=_document_validation_status(response, document.file_id),
                validation_message=_document_validation_message(response, document.file_id),
                metadata_json={
                    "content_keys": sorted(metadata.keys()),
                    "upload": upload_metadata,
                    "classification_rationale": classification.classification.rationale,
                },
            )
        )


def _validation_status(response: ClaimResponse) -> str:
    if response.member_action_required is not None:
        return "ACTION_REQUIRED"
    if response.decision is None:
        return "PENDING"
    return "ADJUDICATED"


def _document_validation_status(response: ClaimResponse, file_id: str) -> str:
    action = response.member_action_required
    if action is None:
        return "VALIDATED"
    if not action.affected_file_ids or file_id in action.affected_file_ids:
        return action.code
    return "VALIDATED"


def _document_validation_message(response: ClaimResponse, file_id: str) -> str | None:
    action = response.member_action_required
    if action is None:
        return None
    if not action.affected_file_ids or file_id in action.affected_file_ids:
        return action.message
    return None
