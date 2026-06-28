"""
Acceptance tests derived directly from test_cases.json.

Each test is named after its case ID and uses the exact input payload defined
in the spec. Cases already covered by test_claims_contract.py (TC001–TC004,
TC006, TC011) are included here for completeness so the full suite of 12 can
be run from a single file.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.models import ClaimSubmission
from app.services.claims_processor import process_claim

client = TestClient(app)


# ---------------------------------------------------------------------------
# TC001 — Wrong Document Uploaded
# ---------------------------------------------------------------------------


def test_tc001_wrong_document_stops_before_decision() -> None:
    response = client.post(
        "/claims/submit",
        json={
            "member_id": "EMP001",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-11-01",
            "claimed_amount": 1500,
            "documents": [
                {"file_id": "F001", "file_name": "dr_sharma_prescription.jpg", "actual_type": "PRESCRIPTION"},
                {"file_id": "F002", "file_name": "another_prescription.jpg", "actual_type": "PRESCRIPTION"},
            ],
        },
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["decision"] is None
    assert payload["status"] == "ACTION_REQUIRED"
    assert payload["member_action_required"]["code"] == "MISSING_REQUIRED_DOCUMENT"
    # Message must name the missing required document type
    assert "hospital bill" in payload["reason"].lower() or "clinic invoice" in payload["reason"].lower()


# ---------------------------------------------------------------------------
# TC002 — Unreadable Document
# ---------------------------------------------------------------------------


def test_tc002_unreadable_document_returns_action_required() -> None:
    response = client.post(
        "/claims/submit",
        json={
            "member_id": "EMP004",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "PHARMACY",
            "treatment_date": "2024-10-25",
            "claimed_amount": 800,
            "documents": [
                {"file_id": "F003", "file_name": "prescription.jpg", "actual_type": "PRESCRIPTION", "quality": "GOOD"},
                {"file_id": "F004", "file_name": "blurry_bill.jpg", "actual_type": "PHARMACY_BILL", "quality": "UNREADABLE"},
            ],
        },
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["decision"] is None
    assert payload["status"] == "ACTION_REQUIRED"
    # Must not hard-reject — action is to re-upload
    assert payload["member_action_required"]["code"] == "UNREADABLE_DOCUMENT"
    assert "blurry_bill.jpg" in payload["reason"]


# ---------------------------------------------------------------------------
# TC003 — Documents Belong to Different Patients
# ---------------------------------------------------------------------------


def test_tc003_conflicting_patient_names_stops_before_decision() -> None:
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
                    "file_id": "F005",
                    "file_name": "prescription_rajesh.jpg",
                    "actual_type": "PRESCRIPTION",
                    "patient_name_on_doc": "Rajesh Kumar",
                },
                {
                    "file_id": "F006",
                    "file_name": "bill_arjun.jpg",
                    "actual_type": "HOSPITAL_BILL",
                    "patient_name_on_doc": "Arjun Mehta",
                },
            ],
        },
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["decision"] is None
    assert payload["status"] == "ACTION_REQUIRED"
    assert payload["member_action_required"]["code"] == "PATIENT_MISMATCH"
    # Both names must be surfaced to the member
    assert "Rajesh Kumar" in payload["reason"]
    assert "Arjun Mehta" in payload["reason"]


# ---------------------------------------------------------------------------
# TC004 — Clean Consultation — Full Approval
# ---------------------------------------------------------------------------


def test_tc004_clean_consultation_approved_with_copay() -> None:
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
                    "content": {
                        "doctor_name": "Dr. Arun Sharma",
                        "doctor_registration": "KA/45678/2015",
                        "patient_name": "Rajesh Kumar",
                        "date": "2024-11-01",
                        "diagnosis": "Viral Fever",
                        "medicines": ["Paracetamol 650mg", "Vitamin C 500mg"],
                    },
                },
                {
                    "file_id": "F008",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {
                        "hospital_name": "City Clinic, Bengaluru",
                        "patient_name": "Rajesh Kumar",
                        "date": "2024-11-01",
                        "line_items": [
                            {"description": "Consultation Fee", "amount": 1000},
                            {"description": "CBC Test", "amount": 300},
                            {"description": "Dengue NS1 Test", "amount": 200},
                        ],
                        "total": 1500,
                    },
                },
            ],
        },
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["status"] == "COMPLETED"
    assert payload["decision"]["decision"] == "APPROVED"
    assert payload["approved_amount"] == 1350  # 10% co-pay deducted
    assert payload["confidence_score"] > 0.85


# ---------------------------------------------------------------------------
# TC005 — Waiting Period (Diabetes)
# ---------------------------------------------------------------------------


def test_tc005_waiting_period_diabetes_rejected() -> None:
    # EMP005 joined 2024-09-01; diabetes has a 90-day waiting period.
    # Treatment on 2024-10-15 is only 44 days after joining.
    response = client.post(
        "/claims/submit",
        json={
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
                        "doctor_name": "Dr. Sunil Mehta",
                        "doctor_registration": "GJ/56789/2014",
                        "patient_name": "Vikram Joshi",
                        "diagnosis": "Type 2 Diabetes Mellitus",
                        "medicines": ["Metformin 500mg", "Glimepiride 1mg"],
                    },
                },
                {
                    "file_id": "F010",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {
                        "patient_name": "Vikram Joshi",
                        "date": "2024-10-15",
                        "total": 3000,
                    },
                },
            ],
        },
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["status"] == "COMPLETED"
    assert payload["decision"]["decision"] == "REJECTED"
    assert "WAITING_PERIOD" in payload["rejection_reasons"]
    # Must tell member when they become eligible
    assert "eligible" in payload["reason"].lower() or "2024-11-30" in payload["reason"]


# ---------------------------------------------------------------------------
# TC006 — Dental Partial Approval (Cosmetic Exclusion)
# ---------------------------------------------------------------------------


def test_tc006_dental_partial_approval_cosmetic_excluded() -> None:
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
                        "hospital_name": "Smile Dental Clinic",
                        "patient_name": "Priya Singh",
                        "line_items": [
                            {"description": "Root Canal Treatment", "amount": 8000},
                            {"description": "Teeth Whitening", "amount": 4000},
                        ],
                        "total": 12000,
                    },
                }
            ],
        },
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["decision"]["decision"] == "PARTIAL"
    assert payload["approved_amount"] == 8000
    # Both line items must be present with correct decisions
    decisions = {item["description"]: item["decision"] for item in payload["line_item_decisions"]}
    assert decisions.get("Root Canal Treatment") == "APPROVED"
    assert decisions.get("Teeth Whitening") == "REJECTED"


# ---------------------------------------------------------------------------
# TC007 — MRI Without Pre-Authorisation
# ---------------------------------------------------------------------------


def test_tc007_mri_without_pre_auth_rejected() -> None:
    response = client.post(
        "/claims/submit",
        json={
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
                        "doctor_name": "Dr. Venkat Rao",
                        "doctor_registration": "AP/67890/2017",
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
        },
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["status"] == "COMPLETED"
    assert payload["decision"]["decision"] == "REJECTED"
    assert "PRE_AUTH_MISSING" in payload["rejection_reasons"]
    # Must explain what the member should do to resubmit
    assert "pre" in payload["reason"].lower()


# ---------------------------------------------------------------------------
# TC008 — Per-Claim Limit Exceeded
# ---------------------------------------------------------------------------


def test_tc008_per_claim_limit_exceeded_rejected() -> None:
    # Per-claim limit: ₹5,000. Claimed: ₹7,500.
    response = client.post(
        "/claims/submit",
        json={
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
                        "doctor_name": "Dr. R. Gupta",
                        "doctor_registration": "DL/34567/2016",
                        "patient_name": "Amit Verma",
                        "diagnosis": "Gastroenteritis",
                        "medicines": ["Antibiotics", "Probiotics", "ORS"],
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
        },
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["status"] == "COMPLETED"
    assert payload["decision"]["decision"] == "REJECTED"
    assert "PER_CLAIM_EXCEEDED" in payload["rejection_reasons"]
    # Must state both the limit and the claimed amount clearly
    reason = payload["reason"]
    assert "5000" in reason or "5,000" in reason
    assert "7500" in reason or "7,500" in reason


# ---------------------------------------------------------------------------
# TC009 — Fraud Signal (Multiple Same-Day Claims)
# ---------------------------------------------------------------------------


def test_tc009_same_day_fraud_signal_routes_to_manual_review() -> None:
    # EMP008 has 3 existing claims on 2024-10-30. This is the 4th.
    # Same-day limit is 2 → fraud detection triggers MANUAL_REVIEW.
    response = client.post(
        "/claims/submit",
        json={
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
                    "content": {
                        "patient_name": "Ravi Menon",
                        "diagnosis": "Migraine",
                        "doctor_name": "Dr. S. Khan",
                    },
                },
                {
                    "file_id": "F018",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {"patient_name": "Ravi Menon", "total": 4800},
                },
            ],
        },
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["status"] == "COMPLETED"
    assert payload["decision"]["decision"] == "MANUAL_REVIEW"
    # Fraud signals must be visible in the output
    fraud_trace = next(
        (item for item in payload["trace"] if "Fraud" in item["component"]),
        None,
    )
    assert fraud_trace is not None


# ---------------------------------------------------------------------------
# TC010 — Network Hospital Discount Applied Before Co-Pay
# ---------------------------------------------------------------------------


def test_tc010_network_hospital_discount_applied_before_copay() -> None:
    # Apollo Hospitals: 20% network discount then 10% co-pay.
    # ₹4,500 → ₹3,600 (after 20% discount) → ₹3,240 (after 10% co-pay).
    response = client.post(
        "/claims/submit",
        json={
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
                        "doctor_name": "Dr. S. Iyer",
                        "doctor_registration": "TN/56789/2013",
                        "patient_name": "Deepak Shah",
                        "diagnosis": "Acute Bronchitis",
                        "medicines": ["Amoxicillin 500mg", "Salbutamol Inhaler"],
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
        },
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["status"] == "COMPLETED"
    assert payload["decision"]["decision"] == "APPROVED"
    assert payload["approved_amount"] == 3240


# ---------------------------------------------------------------------------
# TC011 — Component Failure / Graceful Degradation
# ---------------------------------------------------------------------------


def test_tc011_component_failure_does_not_crash_pipeline() -> None:
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
                {
                    "file_id": "F021",
                    "actual_type": "PRESCRIPTION",
                    "content": {
                        "doctor_name": "Vaidya T. Krishnan",
                        "doctor_registration": "AYUR/KL/2345/2019",
                        "diagnosis": "Chronic Joint Pain",
                        "treatment": "Panchakarma Therapy",
                    },
                },
                {
                    "file_id": "F022",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {
                        "hospital_name": "Ayur Wellness Centre",
                        "total": 4000,
                        "line_items": [
                            {"description": "Panchakarma Therapy (5 sessions)", "amount": 3000},
                            {"description": "Consultation", "amount": 1000},
                        ],
                    },
                },
            ],
        },
    )

    payload = response.json()
    # Must not return 500
    assert response.status_code == 202
    assert payload["decision"]["decision"] == "APPROVED"
    # Component failure must be surfaced
    assert len(payload["component_failures"]) > 0
    # Confidence must be lower than a normal full-pipeline approval
    assert payload["confidence_score"] < 0.85


# ---------------------------------------------------------------------------
# TC012 — Excluded Treatment (Bariatric / Obesity)
# ---------------------------------------------------------------------------


def test_tc012_excluded_condition_obesity_rejected() -> None:
    response = client.post(
        "/claims/submit",
        json={
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
                        "doctor_name": "Dr. P. Banerjee",
                        "doctor_registration": "WB/34567/2015",
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
        },
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["status"] == "COMPLETED"
    assert payload["decision"]["decision"] == "REJECTED"
    assert "EXCLUDED_CONDITION" in payload["rejection_reasons"]
    assert payload["confidence_score"] > 0.90
