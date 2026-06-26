from fastapi.testclient import TestClient

from app.main import app


def test_submit_claim_returns_standard_response_shape() -> None:
    client = TestClient(app)

    response = client.post(
        "/claims/submit",
        json={
            "member_id": "EMP001",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-11-01",
            "claimed_amount": 1500,
            "documents": [
                {
                    "file_id": "F001",
                    "file_name": "prescription.jpg",
                    "actual_type": "PRESCRIPTION",
                    "quality": "GOOD",
                }
            ],
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["claim_id"].startswith("CLM_")
    assert payload["status"] == "ACTION_REQUIRED"
    assert payload["decision"] is None
    assert payload["approved_amount"] is None
    assert payload["confidence_score"] is None
    assert payload["rejection_reasons"] == []
    assert payload["line_item_decisions"] == []
    assert payload["member_action_required"]["code"] == "MISSING_REQUIRED_DOCUMENT"
    assert payload["retrieved_policy_evidence"] != []
    assert payload["component_failures"] == []
    assert payload["trace"][0]["component"] == "ClaimIntakeAPI"
    assert "HOSPITAL_BILL" in payload["reason"]


def test_get_claim_returns_previously_submitted_claim() -> None:
    client = TestClient(app)

    created = client.post(
        "/claims/submit",
        json={
            "member_id": "EMP002",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "DENTAL",
            "treatment_date": "2024-10-15",
            "claimed_amount": 12000,
            "documents": [{"file_id": "F011", "actual_type": "HOSPITAL_BILL"}],
        },
    ).json()

    response = client.get(f"/claims/{created['claim_id']}")

    assert response.status_code == 200
    assert response.json()["claim_id"] == created["claim_id"]


def test_get_unknown_claim_returns_404() -> None:
    client = TestClient(app)

    response = client.get("/claims/CLM_DOES_NOT_EXIST")

    assert response.status_code == 404
    assert "was not found" in response.json()["detail"]


def test_submit_claim_requires_at_least_one_document() -> None:
    client = TestClient(app)

    response = client.post(
        "/claims/submit",
        json={
            "member_id": "EMP001",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-11-01",
            "claimed_amount": 1500,
            "documents": [],
        },
    )

    assert response.status_code == 422


def test_clean_consultation_applies_copay() -> None:
    client = TestClient(app)

    response = client.post(
        "/claims/submit",
        json={
            "member_id": "EMP001",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-11-01",
            "claimed_amount": 1500,
            "ytd_claims_amount": 5000,
            "documents": [
                {
                    "file_id": "F007",
                    "actual_type": "PRESCRIPTION",
                    "content": {"patient_name": "Rajesh Kumar", "diagnosis": "Viral Fever"},
                },
                {
                    "file_id": "F008",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {"patient_name": "Rajesh Kumar", "total": 1500},
                },
            ],
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["decision"]["decision"] == "APPROVED"
    assert payload["approved_amount"] == 1350
    assert payload["confidence_score"] > 0.85


def test_submit_claim_rejects_mismatched_policy_id() -> None:
    client = TestClient(app)

    response = client.post(
        "/claims/submit",
        json={
            "member_id": "EMP001",
            "policy_id": "OTHER_POLICY",
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-11-01",
            "claimed_amount": 1500,
            "documents": [
                {
                    "file_id": "F007",
                    "actual_type": "PRESCRIPTION",
                    "quality": "GOOD",
                },
                {
                    "file_id": "F008",
                    "actual_type": "HOSPITAL_BILL",
                    "quality": "GOOD",
                },
            ],
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["decision"]["decision"] == "REJECTED"
    assert "POLICY_MISMATCH" in payload["rejection_reasons"]


def test_dental_claim_partially_approves_covered_line_items() -> None:
    client = TestClient(app)

    response = client.post(
        "/claims/submit",
        json={
            "member_id": "EMP002",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "DENTAL",
            "treatment_date": "2024-10-15",
            "claimed_amount": 12000,
            "documents": [
                {
                    "file_id": "F011",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {
                        "patient_name": "Priya Singh",
                        "line_items": [
                            {"description": "Root Canal Treatment", "amount": 8000},
                            {"description": "Teeth Whitening", "amount": 4000},
                        ],
                    },
                }
            ],
        },
    )

    payload = response.json()
    assert payload["decision"]["decision"] == "PARTIAL"
    assert payload["approved_amount"] == 8000
    assert payload["line_item_decisions"][1]["decision"] == "REJECTED"


def test_component_failure_is_visible_without_crashing() -> None:
    client = TestClient(app)

    response = client.post(
        "/claims/submit",
        json={
            "member_id": "EMP006",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "ALTERNATIVE_MEDICINE",
            "treatment_date": "2024-10-28",
            "claimed_amount": 4000,
            "simulate_component_failure": True,
            "documents": [
                {"file_id": "F021", "actual_type": "PRESCRIPTION", "content": {"diagnosis": "Joint Pain"}},
                {"file_id": "F022", "actual_type": "HOSPITAL_BILL", "content": {"total": 4000}},
            ],
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["decision"]["decision"] == "APPROVED"
    assert payload["component_failures"][0]["component"] == "PolicyEvidenceRetriever"
    assert payload["confidence_score"] < 0.85
