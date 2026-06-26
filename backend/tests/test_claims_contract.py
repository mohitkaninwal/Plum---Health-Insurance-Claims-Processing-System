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
    assert payload["status"] == "RECEIVED"
    assert payload["decision"] is None
    assert payload["approved_amount"] is None
    assert payload["confidence_score"] is None
    assert payload["rejection_reasons"] == []
    assert payload["line_item_decisions"] == []
    assert payload["member_action_required"] is None
    assert payload["retrieved_policy_evidence"] == []
    assert payload["component_failures"] == []
    assert payload["trace"][0]["component"] == "ClaimIntakeAPI"


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

