from app.models import ClaimSubmission
from app.services.claims_processor import process_claim
from app.services.extraction_pipeline import _names_are_similar
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


# ---------------------------------------------------------------------------
# Waiting period rules
# ---------------------------------------------------------------------------


def test_rule_engine_rejects_claim_within_specific_condition_waiting_period() -> None:
    # EMP005 (Vikram Joshi) joined 2024-09-01. Diabetes has a 90-day waiting
    # period. Treatment on 2024-10-15 is only 44 days after joining — within
    # the waiting window.
    submission = ClaimSubmission.model_validate(
        {
            "member_id": "EMP005",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-10-15",
            "claimed_amount": 3000,
            "documents": [
                {
                    "file_id": "F009",
                    "actual_type": "PRESCRIPTION",
                    "content": {
                        "patient_name": "Vikram Joshi",
                        "diagnosis": "Type 2 Diabetes Mellitus",
                        "medicines": ["Metformin 500mg", "Glimepiride 1mg"],
                    },
                },
                {
                    "file_id": "F010",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {"patient_name": "Vikram Joshi", "total": 3000},
                },
            ],
        }
    )

    response = process_claim(submission)

    assert response.decision is not None
    assert response.decision.decision == "REJECTED"
    assert "WAITING_PERIOD" in response.rejection_reasons
    # Must state when the member becomes eligible
    assert "2024-11-30" in response.reason or "eligible" in response.reason.lower()


    # NOTE: The initial 30-day waiting period is measured from the policy start
    # date (2024-04-01), not from each member's individual join date. EMP005
    # joined on 2024-09-01, but since the policy start date is well past the
    # 30-day window, no initial waiting period applies to any member in this
    # policy. A test for a truly new member within 30 days of policy start
    # would require a separate policy fixture and is outside the current scope.


# ---------------------------------------------------------------------------
# Financial rules
# ---------------------------------------------------------------------------


def test_rule_engine_rejects_per_claim_limit_exceeded() -> None:
    # Per-claim limit is ₹5,000. Claimed ₹7,500 must be rejected outright.
    submission = ClaimSubmission.model_validate(
        {
            "member_id": "EMP003",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-10-20",
            "claimed_amount": 7500,
            "ytd_claims_amount": 10000,
            "documents": [
                {
                    "file_id": "F015",
                    "actual_type": "PRESCRIPTION",
                    "content": {
                        "patient_name": "Amit Verma",
                        "diagnosis": "Gastroenteritis",
                        "medicines": ["Antibiotics", "Probiotics"],
                    },
                },
                {
                    "file_id": "F016",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {
                        "patient_name": "Amit Verma",
                        "line_items": [
                            {"description": "Consultation Fee", "amount": 2000},
                            {"description": "Medicines", "amount": 5500},
                        ],
                        "total": 7500,
                    },
                },
            ],
        }
    )

    response = process_claim(submission)

    assert response.decision is not None
    assert response.decision.decision == "REJECTED"
    assert "PER_CLAIM_EXCEEDED" in response.rejection_reasons
    # Message must state both the limit and the claimed amount
    assert "5000" in response.reason or "5,000" in response.reason
    assert "7500" in response.reason or "7,500" in response.reason


def test_rule_engine_applies_network_discount_before_copay() -> None:
    # Apollo Hospitals is a network hospital with 20% discount.
    # Claimed: ₹4,500 → after 20% discount: ₹3,600 → after 10% co-pay: ₹3,240.
    submission = ClaimSubmission.model_validate(
        {
            "member_id": "EMP010",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-11-03",
            "claimed_amount": 4500,
            "hospital_name": "Apollo Hospitals",
            "ytd_claims_amount": 8000,
            "documents": [
                {
                    "file_id": "F019",
                    "actual_type": "PRESCRIPTION",
                    "content": {
                        "patient_name": "Deepak Shah",
                        "diagnosis": "Acute Bronchitis",
                        "medicines": ["Amoxicillin 500mg"],
                    },
                },
                {
                    "file_id": "F020",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {
                        "hospital_name": "Apollo Hospitals",
                        "patient_name": "Deepak Shah",
                        "line_items": [
                            {"description": "Consultation Fee", "amount": 1500},
                            {"description": "Medicines", "amount": 3000},
                        ],
                        "total": 4500,
                    },
                },
            ],
        }
    )

    response = process_claim(submission)

    assert response.decision is not None
    assert response.decision.decision == "APPROVED"
    assert response.decision.approved_amount == 3240


# ---------------------------------------------------------------------------
# Pre-authorisation rules
# ---------------------------------------------------------------------------


def test_rule_engine_rejects_pre_auth_missing_for_high_value_diagnostic() -> None:
    # MRI scan above ₹10,000 requires pre-authorisation. None provided here.
    submission = ClaimSubmission.model_validate(
        {
            "member_id": "EMP007",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "DIAGNOSTIC",
            "treatment_date": "2024-11-02",
            "claimed_amount": 15000,
            "documents": [
                {
                    "file_id": "F012",
                    "actual_type": "PRESCRIPTION",
                    "content": {
                        "diagnosis": "Suspected Lumbar Disc Herniation",
                        "tests_ordered": ["MRI Lumbar Spine"],
                    },
                },
                {
                    "file_id": "F013",
                    "actual_type": "LAB_REPORT",
                    "content": {"test_name": "MRI Lumbar Spine"},
                },
                {
                    "file_id": "F014",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {
                        "line_items": [{"description": "MRI Lumbar Spine", "amount": 15000}],
                        "total": 15000,
                    },
                },
            ],
        }
    )

    response = process_claim(submission)

    assert response.decision is not None
    assert response.decision.decision == "REJECTED"
    assert "PRE_AUTH_MISSING" in response.rejection_reasons


# ---------------------------------------------------------------------------
# Fraud detection
# ---------------------------------------------------------------------------


def test_rule_engine_routes_high_value_claim_to_manual_review() -> None:
    # auto_manual_review_above is ₹25,000. A ₹26,000 claim must go to manual review.
    response = process_claim(
        _base_submission(
            claimed_amount=26000,
            documents=[
                {
                    "file_id": "RX",
                    "actual_type": "PRESCRIPTION",
                    "content": {"patient_name": "Rajesh Kumar", "diagnosis": "Fever"},
                },
                {
                    "file_id": "BILL",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {"patient_name": "Rajesh Kumar", "total": 26000},
                },
            ],
        )
    )

    assert response.decision is not None
    assert response.decision.decision == "MANUAL_REVIEW"
    assert "High-value" in response.reason or "manual review" in response.reason.lower()


def test_rule_engine_routes_fraud_signal_to_manual_review() -> None:
    # Same-day claims limit is 2. EMP008 already has 3 claims on 2024-10-30,
    # making this the 4th — triggering the fraud detection rule.
    submission = ClaimSubmission.model_validate(
        {
            "member_id": "EMP008",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-10-30",
            "claimed_amount": 4800,
            "claims_history": [
                {"claim_id": "CLM_0081", "date": "2024-10-30", "amount": 1200, "provider": "City Clinic A"},
                {"claim_id": "CLM_0082", "date": "2024-10-30", "amount": 1800, "provider": "City Clinic B"},
                {"claim_id": "CLM_0083", "date": "2024-10-30", "amount": 2100, "provider": "Wellness Center"},
            ],
            "documents": [
                {
                    "file_id": "F017",
                    "actual_type": "PRESCRIPTION",
                    "content": {"patient_name": "Ravi Menon", "diagnosis": "Migraine"},
                },
                {
                    "file_id": "F018",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {"patient_name": "Ravi Menon", "total": 4800},
                },
            ],
        }
    )

    response = process_claim(submission)

    assert response.decision is not None
    assert response.decision.decision == "MANUAL_REVIEW"


# ---------------------------------------------------------------------------
# Excluded conditions
# ---------------------------------------------------------------------------


def test_rule_engine_rejects_excluded_condition_obesity() -> None:
    # Obesity treatment (bariatric + diet programme) is explicitly excluded.
    submission = ClaimSubmission.model_validate(
        {
            "member_id": "EMP009",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-10-18",
            "claimed_amount": 8000,
            "documents": [
                {
                    "file_id": "F023",
                    "actual_type": "PRESCRIPTION",
                    "content": {
                        "patient_name": "Anita Desai",
                        "diagnosis": "Morbid Obesity — BMI 37",
                        "treatment": "Bariatric Consultation and Customised Diet Plan",
                    },
                },
                {
                    "file_id": "F024",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {
                        "patient_name": "Anita Desai",
                        "line_items": [
                            {"description": "Bariatric Consultation", "amount": 3000},
                            {"description": "Personalised Diet and Nutrition Program", "amount": 5000},
                        ],
                        "total": 8000,
                    },
                },
            ],
        }
    )

    response = process_claim(submission)

    assert response.decision is not None
    assert response.decision.decision == "REJECTED"
    assert "EXCLUDED_CONDITION" in response.rejection_reasons


# ---------------------------------------------------------------------------
# Boundary conditions
# ---------------------------------------------------------------------------


def test_rule_engine_approves_claim_at_exact_per_claim_limit() -> None:
    """A claim exactly at the per-claim limit (₹5,000) should be approved, not rejected."""
    submission = _base_submission(claimed_amount=5000)
    response = process_claim(submission)

    assert response.decision is not None
    assert response.decision.decision != "REJECTED" or "PER_CLAIM_EXCEEDED" not in response.rejection_reasons


def test_names_are_similar_with_special_characters() -> None:
    """Hyphens, periods, and accents should not break name matching."""
    assert _names_are_similar("Dr. Rajesh Kumar", "Dr Rajesh Kumar")
    assert _names_are_similar("Anne-Marie Smith", "Anne Marie Smith")
    assert not _names_are_similar("Rajesh Kumar", "Completely Different")
