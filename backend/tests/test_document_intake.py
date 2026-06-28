"""Tests for document_intake.py — filename inference and classification fallback."""
from __future__ import annotations

import logging
from unittest.mock import patch, MagicMock

from app.models import DocumentQuality, DocumentType, UploadedDocument
from app.services.document_intake import classify_document, _classify_with_groq_vision


def _doc(
    file_id: str = "F001",
    file_name: str | None = None,
    actual_type: DocumentType | None = None,
    declared_type: DocumentType | None = None,
    quality: DocumentQuality | None = None,
) -> UploadedDocument:
    return UploadedDocument(
        file_id=file_id,
        file_name=file_name,
        actual_type=actual_type,
        declared_type=declared_type,
        quality=quality,
    )


def test_classify_uses_actual_type_when_set() -> None:
    result = classify_document(_doc(actual_type=DocumentType.HOSPITAL_BILL))

    assert result.classification.document_type == DocumentType.HOSPITAL_BILL
    assert result.classification.confidence == 1.0
    assert result.source == "fixture"


def test_classify_infers_prescription_from_filename() -> None:
    result = classify_document(_doc(file_name="prescription.jpg"))

    assert result.classification.document_type == DocumentType.PRESCRIPTION
    assert result.source == "preprocessing"


def test_classify_infers_hospital_bill_from_filename() -> None:
    for name in ("hospital_bill.pdf", "clinic_invoice.jpg", "medical_bill.png"):
        result = classify_document(_doc(file_name=name))
        assert result.classification.document_type == DocumentType.HOSPITAL_BILL, f"failed for {name}"


def test_classify_infers_lab_report_from_filename() -> None:
    for name in ("lab_report.pdf", "lab_test.jpg"):
        result = classify_document(_doc(file_name=name))
        assert result.classification.document_type == DocumentType.LAB_REPORT, f"failed for {name}"


def test_classify_infers_pharmacy_bill_from_filename() -> None:
    for name in ("pharmacy_bill.pdf", "medicine_bill.jpg", "drug_bill.pdf"):
        result = classify_document(_doc(file_name=name))
        assert result.classification.document_type == DocumentType.PHARMACY_BILL, f"failed for {name}"


def test_classify_uses_declared_type_as_fallback() -> None:
    result = classify_document(_doc(file_name="random_doc.pdf", declared_type=DocumentType.DISCHARGE_SUMMARY))

    assert result.classification.document_type == DocumentType.DISCHARGE_SUMMARY
    assert result.source == "declared"


def test_classify_returns_unknown_when_no_signal() -> None:
    result = classify_document(_doc(file_name="attachment_xyz.pdf"))

    assert result.classification.document_type == DocumentType.UNKNOWN
    assert result.source == "unknown"


def test_classify_marks_unreadable_document_as_unknown() -> None:
    result = classify_document(_doc(file_name="blurry.jpg", quality=DocumentQuality.UNREADABLE))

    assert result.classification.document_type == DocumentType.UNKNOWN
    assert result.source == "quality"
    assert result.classification.confidence == 0.0


def test_classify_infers_dental_report_from_filename() -> None:
    for name in ("dental_report.pdf", "dental_xray.jpg", "dental_invoice.pdf"):
        result = classify_document(_doc(file_name=name))
        assert result.classification.document_type == DocumentType.DENTAL_REPORT, f"failed for {name}"


# ---------------------------------------------------------------------------
# Groq vision failure paths
# ---------------------------------------------------------------------------


def test_classify_with_groq_vision_logs_warning_on_failure() -> None:
    """When Groq vision classification fails, it should log a warning and return the original document."""
    document = _doc(file_id="IMG1", file_name="scan.jpg")
    content = b"fake image bytes"

    import app.services.document_intake as di

    with patch.object(di.logger, "warning") as mock_warn:
        with patch("groq.Groq", side_effect=Exception("API down")):
            result = _classify_with_groq_vision(document, content, "image/jpeg")

    mock_warn.assert_called_once()
    assert "IMG1" in str(mock_warn.call_args)
    assert result.file_id == "IMG1"
    assert result.actual_type is None  # unchanged


def test_pdf_extraction_handles_corrupted_bytes() -> None:
    """Corrupted PDF bytes should not crash _uploaded_text; it should return None."""
    from app.services.extraction_pipeline import _uploaded_text

    result = _uploaded_text(b"\x00\x01\x02garbage", "application/pdf", "corrupted.pdf")
    assert result is None
