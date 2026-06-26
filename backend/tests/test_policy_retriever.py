from pathlib import Path

from app.models import ClaimSubmission
from app.services.policy_loader import read_policy_terms
from app.services.policy_retriever import (
    build_policy_knowledge_base,
    reciprocal_rank_fusion,
    retrieve_policy_evidence,
)


def test_policy_knowledge_base_chunks_policy_json_and_document_guide(tmp_path: Path) -> None:
    policy = read_policy_terms()
    guide = tmp_path / "sample_documents_guide.md"
    guide.write_text(
        """
# Guide

### 1. Medical Prescription
**Key fields to extract:**
- Patient name
- Diagnosis

### 2. Hospital Bill / Clinic Invoice
**Key fields to extract:**
- Total amount
""",
        encoding="utf-8",
    )

    chunks = build_policy_knowledge_base(policy, guide)
    evidence_ids = {chunk.evidence_id for chunk in chunks}

    assert "POLICY_DOCUMENT_REQUIREMENTS_CONSULTATION" in evidence_ids
    assert "POLICY_OPD_CATEGORY_CONSULTATION" in evidence_ids
    assert "POLICY_WAITING_PERIODS" in evidence_ids
    assert "DOC_GUIDE_MEDICAL_PRESCRIPTION" in evidence_ids
    assert all(len(chunk.embedding) == 64 for chunk in chunks)


def test_rrf_combines_dense_and_lexical_rankings() -> None:
    fused = reciprocal_rank_fusion(["A", "B", "C"], ["C", "A"])

    assert fused["A"] > fused["B"]
    assert fused["C"] > fused["B"]


def test_retrieve_policy_evidence_prefers_claim_category_rules() -> None:
    policy = read_policy_terms()
    submission = ClaimSubmission.model_validate(
        {
            "member_id": "EMP001",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-11-01",
            "claimed_amount": 1500,
            "documents": [
                {"file_id": "F001", "actual_type": "PRESCRIPTION"},
                {"file_id": "F002", "actual_type": "HOSPITAL_BILL"},
            ],
        }
    )

    evidence = retrieve_policy_evidence(submission, policy, limit=4)

    assert evidence
    assert any(item.evidence_id == "POLICY_DOCUMENT_REQUIREMENTS_CONSULTATION" for item in evidence)
    assert any(item.rrf_score is not None for item in evidence)
