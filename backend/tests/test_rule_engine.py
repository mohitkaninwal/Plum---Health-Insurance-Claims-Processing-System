from app.models import ClaimSubmission
from app.services.claims_processor import process_claim
from app.services.policy_loader import read_policy_terms


def _base_submission(**overrides: object) -> ClaimSubmission:
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
                "content": {"patient_name": "Rajesh Kumar", "diagnosis": "Viral Fever"},
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


def test_rule_engine_rejects_claims_below_minimum_amount() -> None:
    response = process_claim(_base_submission(claimed_amount=400))

    assert response.decision is not None
    assert response.decision.decision == "REJECTED"
    assert "SUBMISSION_RULE_FAILED" in response.rejection_reasons
    assert "minimum claim amount" in response.reason


def test_rule_engine_rejects_late_submissions_when_submission_date_is_available() -> None:
    submission = _base_submission(
        documents=[
            {
                "file_id": "RX",
                "actual_type": "PRESCRIPTION",
                "content": {
                    "patient_name": "Rajesh Kumar",
                    "diagnosis": "Viral Fever",
                    "submission_date": "2024-12-15",
                },
            },
            {
                "file_id": "BILL",
                "actual_type": "HOSPITAL_BILL",
                "content": {"patient_name": "Rajesh Kumar", "total": 1500},
            },
        ],
    )

    response = process_claim(submission)

    assert response.decision is not None
    assert response.decision.decision == "REJECTED"
    assert "SUBMISSION_RULE_FAILED" in response.rejection_reasons
    assert "44 days after treatment" in response.reason


def test_rule_engine_rejects_treatment_outside_policy_period() -> None:
    response = process_claim(_base_submission(treatment_date="2025-04-01"))

    assert response.decision is not None
    assert response.decision.decision == "REJECTED"
    assert "POLICY_NOT_ACTIVE" in response.rejection_reasons
    assert "after policy end date" in response.reason


def test_rule_engine_rejects_annual_opd_limit_excess() -> None:
    response = process_claim(_base_submission(ytd_claims_amount=49500, claimed_amount=1500))

    assert response.decision is not None
    assert response.decision.decision == "REJECTED"
    assert "ANNUAL_OPD_LIMIT_EXCEEDED" in response.rejection_reasons
    assert "annual OPD limit" in response.reason


def test_rule_engine_rejects_uncovered_categories_from_policy_config() -> None:
    policy = read_policy_terms()
    vision_config = policy.opd_categories["vision"].model_copy(update={"covered": False})
    policy = policy.model_copy(
        update={"opd_categories": {**policy.opd_categories, "vision": vision_config}}
    )
    submission = ClaimSubmission.model_validate(
        {
            "member_id": "EMP001",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "VISION",
            "treatment_date": "2024-11-01",
            "claimed_amount": 1500,
            "documents": [
                {"file_id": "RX", "actual_type": "PRESCRIPTION"},
                {"file_id": "BILL", "actual_type": "HOSPITAL_BILL"},
            ],
        }
    )

    response = process_claim(submission, policy)

    assert response.decision is not None
    assert response.decision.decision == "REJECTED"
    assert "CATEGORY_NOT_COVERED" in response.rejection_reasons


def test_rule_engine_rejects_all_excluded_dental_line_items() -> None:
    submission = ClaimSubmission.model_validate(
        {
            "member_id": "EMP002",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "DENTAL",
            "treatment_date": "2024-10-15",
            "claimed_amount": 4000,
            "documents": [
                {
                    "file_id": "BILL",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {
                        "patient_name": "Priya Singh",
                        "line_items": [{"description": "Teeth Whitening", "amount": 4000}],
                    },
                }
            ],
        }
    )

    response = process_claim(submission)

    assert response.decision is not None
    assert response.decision.decision == "REJECTED"
    assert "EXCLUDED_DENTAL_PROCEDURE" in response.rejection_reasons
    assert response.line_item_decisions[0].decision == "REJECTED"


def test_rule_engine_rejects_excluded_vision_items() -> None:
    submission = ClaimSubmission.model_validate(
        {
            "member_id": "EMP001",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "VISION",
            "treatment_date": "2024-11-01",
            "claimed_amount": 12000,
            "documents": [
                {"file_id": "RX", "actual_type": "PRESCRIPTION"},
                {
                    "file_id": "BILL",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {
                        "line_items": [{"description": "LASIK Surgery", "amount": 12000}]
                    },
                },
            ],
        }
    )

    response = process_claim(submission)

    assert response.decision is not None
    assert response.decision.decision == "REJECTED"
    assert "EXCLUDED_VISION_ITEM" in response.rejection_reasons
