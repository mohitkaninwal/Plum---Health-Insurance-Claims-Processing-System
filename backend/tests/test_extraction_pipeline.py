"""Tests for extraction_pipeline.py — graph compilation, patient mismatch, SHA256 cache."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.models import ClaimSubmission, DocumentQuality, DocumentType
from app.services.extraction_pipeline import (
    _EXTRACTION_CACHE,
    _EXTRACTION_CACHE_MAX,
    _call_groq_with_retry,
    _names_are_similar,
    _strip_billing_fields_if_not_bill,
    run_extraction_pipeline,
)


def _make_submission(**overrides: object) -> ClaimSubmission:
    payload = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": 1500,
        "documents": [
            {
                "file_id": "RX",
                "actual_type": "PRESCRIPTION",
                "content": {"patient_name": "Rajesh Kumar", "diagnosis": "Fever"},
            },
            {
                "file_id": "BILL",
                "actual_type": "HOSPITAL_BILL",
                "content": {"patient_name": "Rajesh Kumar", "total": 1500},
            },
        ],
    }
    payload.update(overrides)
    return ClaimSubmission.model_validate(payload)


def test_extraction_pipeline_graph_compiles_without_error() -> None:
    """run_extraction_pipeline should compile and execute the LangGraph without raising."""
    submission = _make_submission()
    result = run_extraction_pipeline(submission)

    assert result is not None
    assert len(result.extracted_documents) == 2
    assert result.member_action_required is None


def test_extraction_pipeline_extracts_fixture_fields() -> None:
    submission = _make_submission()
    result = run_extraction_pipeline(submission)

    rx = next(d for d in result.extracted_documents if d.file_id == "RX")
    assert rx.document_type == DocumentType.PRESCRIPTION
    assert rx.fields.get("patient_name") == "Rajesh Kumar"


def test_extraction_pipeline_detects_patient_mismatch() -> None:
    """Two documents with different patient names should trigger PATIENT_MISMATCH action."""
    submission = _make_submission(
        documents=[
            {
                "file_id": "RX",
                "actual_type": "PRESCRIPTION",
                "content": {"patient_name": "Rajesh Kumar", "diagnosis": "Fever"},
            },
            {
                "file_id": "BILL",
                "actual_type": "HOSPITAL_BILL",
                "content": {"patient_name": "Priya Singh", "total": 1500},
            },
        ]
    )
    result = run_extraction_pipeline(submission)

    assert result.member_action_required is not None
    assert result.member_action_required.code == "PATIENT_MISMATCH"


def test_names_are_similar_handles_minor_variations() -> None:
    assert _names_are_similar("rajesh kumar", "Rajesh Kumar")
    assert _names_are_similar("rajesh  kumar", "rajesh kumar")
    assert not _names_are_similar("rajesh kumar", "priya singh")


def test_names_are_similar_fuzzy_threshold() -> None:
    # Names that are slightly different (typo) should still match above threshold
    assert _names_are_similar("rajesh kumar", "rajesh kumaR")
    # Very different names should not match
    assert not _names_are_similar("rajesh kumar", "anita desai")


def test_extraction_cache_stores_and_returns_cached_result() -> None:
    """A second call with the same SHA256 should return the cached result."""
    _EXTRACTION_CACHE.clear()

    sha256 = "test_sha256_abc123"
    fake_upload = {
        "base64": "dGVzdA==",  # "test" in base64
        "content_type": "image/jpeg",
        "sha256": sha256,
    }
    submission = _make_submission(
        documents=[
            {
                "file_id": "IMG1",
                "file_name": "bill.jpg",
                "content": {"upload": fake_upload},
            }
        ]
    )

    fake_payload = SimpleNamespace(
        fields={"patient_name": "Rajesh Kumar", "total": 1500.0},
        missing_fields=[],
        confidence=0.92,
        warnings=[],
    )
    with patch(
        "app.services.extraction_pipeline._request_groq_extraction",
        return_value=fake_payload,
    ):
        result1 = run_extraction_pipeline(submission)

    assert sha256 in _EXTRACTION_CACHE

    with patch(
        "app.services.extraction_pipeline._request_groq_extraction",
        side_effect=AssertionError("Should not call Groq on cache hit"),
    ):
        result2 = run_extraction_pipeline(submission)

    assert result2 is not None
    _EXTRACTION_CACHE.clear()


def test_extraction_cache_evicts_oldest_entry_when_full() -> None:
    """Cache should not grow beyond _EXTRACTION_CACHE_MAX entries."""
    from collections import OrderedDict
    import app.services.extraction_pipeline as ep

    original_cache = ep._EXTRACTION_CACHE
    ep._EXTRACTION_CACHE = OrderedDict()

    for i in range(_EXTRACTION_CACHE_MAX + 5):
        ep._EXTRACTION_CACHE[f"key_{i}"] = f"value_{i}"
        if len(ep._EXTRACTION_CACHE) > _EXTRACTION_CACHE_MAX:
            ep._EXTRACTION_CACHE.popitem(last=False)

    assert len(ep._EXTRACTION_CACHE) == _EXTRACTION_CACHE_MAX
    ep._EXTRACTION_CACHE = original_cache


def test_strip_billing_fields_removes_total_from_lab_report() -> None:
    fields = {"patient_name": "Rajesh Kumar", "test_name": "CBC", "total": 2500.0, "line_items": []}
    filtered = _strip_billing_fields_if_not_bill(fields, DocumentType.LAB_REPORT)

    assert "total" not in filtered
    assert "line_items" not in filtered
    assert filtered["patient_name"] == "Rajesh Kumar"
    assert filtered["test_name"] == "CBC"


def test_strip_billing_fields_keeps_total_for_hospital_bill() -> None:
    fields = {"patient_name": "Rajesh Kumar", "total": 2500.0, "line_items": []}
    filtered = _strip_billing_fields_if_not_bill(fields, DocumentType.HOSPITAL_BILL)

    assert "total" in filtered
    assert "line_items" in filtered


def test_claims_processor_stops_for_unreadable_documents() -> None:
    """Documents explicitly marked UNREADABLE trigger UNREADABLE_DOCUMENT via document rules."""
    from app.services.claims_processor import process_claim

    submission = _make_submission(
        documents=[
            {
                "file_id": "BAD",
                "file_name": "blurry_scan.jpg",
                "actual_type": "PRESCRIPTION",
                "quality": "UNREADABLE",
            },
            {
                "file_id": "BILL",
                "actual_type": "HOSPITAL_BILL",
                "content": {"patient_name": "Rajesh Kumar", "total": 1500},
            },
        ]
    )
    response = process_claim(submission)

    assert response.status == "ACTION_REQUIRED"
    assert response.member_action_required is not None
    assert response.member_action_required.code == "UNREADABLE_DOCUMENT"


# ---------------------------------------------------------------------------
# Groq retry / failure path tests
# ---------------------------------------------------------------------------


class _RateLimitError(Exception):
    """Simulates a Groq RateLimitError for retry testing."""
    pass


# Make the class name match what _groq_retryable checks
_RateLimitError.__name__ = "RateLimitError"


def test_groq_retry_exhaustion_propagates_error() -> None:
    """After 3 consecutive retryable errors, _call_groq_with_retry should raise."""
    client = MagicMock()
    client.chat.completions.create.side_effect = _RateLimitError("rate limited")

    with patch("app.services.extraction_pipeline.time.sleep"):
        try:
            _call_groq_with_retry(client, model="test-model", messages=[])
            assert False, "Expected _RateLimitError to be raised"
        except _RateLimitError:
            pass

    assert client.chat.completions.create.call_count == 3


def test_call_groq_with_retry_succeeds_on_second_attempt() -> None:
    """First call fails with a retryable error, second succeeds."""
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"fields":{}}'))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _RateLimitError("rate limited"),
        fake_response,
    ]

    with patch("app.services.extraction_pipeline.time.sleep"):
        result = _call_groq_with_retry(client, model="test-model", messages=[])

    assert result is fake_response
    assert client.chat.completions.create.call_count == 2


def test_groq_empty_response_returns_empty_extraction() -> None:
    """When Groq returns empty content, extraction should still produce a result."""
    fake_payload = SimpleNamespace(
        fields={},
        missing_fields=["patient_name", "diagnosis"],
        confidence=0.0,
        warnings=["Empty response from LLM"],
    )
    submission = _make_submission(
        documents=[
            {
                "file_id": "IMG1",
                "file_name": "bill.jpg",
                "content": {
                    "upload": {
                        "base64": "dGVzdA==",
                        "content_type": "image/jpeg",
                        "sha256": "empty_test_sha",
                    }
                },
            }
        ]
    )

    with patch(
        "app.services.extraction_pipeline._request_groq_extraction",
        return_value=fake_payload,
    ):
        result = run_extraction_pipeline(submission)

    assert result is not None
    assert len(result.extracted_documents) == 1
    assert result.extracted_documents[0].fields == {}
