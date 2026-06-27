import base64
from io import BytesIO
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.api.claims as claims_api
from app.main import app
from app.services import extraction_pipeline
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def _pdf_bytes(lines: list[str]) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    def escape_pdf_text(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content = "BT /F1 12 Tf 72 720 Td " + " ".join(
        [f"({escape_pdf_text(line)}) Tj 0 -18 Td" for line in lines]
    ) + " ET"
    stream = DecodedStreamObject()
    stream.set_data(content.encode("utf-8"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


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
    assert payload["trace"][1]["component"] == "DocumentClassifier"
    assert "HOSPITAL_BILL" in payload["reason"]
    assert "only PRESCRIPTION documents were uploaded" in payload["reason"]


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


def test_get_claim_context_returns_policy_and_members() -> None:
    client = TestClient(app)

    response = client.get("/claims/context")

    payload = response.json()
    assert response.status_code == 200
    assert payload["policy_id"] == "PLUM_GHI_2024"
    assert payload["company_name"] == "TechCorp Solutions Pvt Ltd"
    assert payload["members"][0]["member_id"] == "EMP001"
    assert payload["members"][0]["name"] == "Rajesh Kumar"
    assert "DEP001" in payload["members"][0]["dependents"]
    assert "DEP003" in payload["unresolved_dependent_ids"]


def test_submit_claim_stops_for_patient_not_in_selected_member_family() -> None:
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
                    "file_id": "F050",
                    "file_name": "prescription.jpg",
                    "actual_type": "PRESCRIPTION",
                    "content": {"patient_name": "Meera Deshpande", "diagnosis": "Viral Fever"},
                },
                {
                    "file_id": "F051",
                    "file_name": "hospital_bill.jpg",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {"patient_name": "Meera Deshpande", "total": 1500},
                }
            ],
        },
    )

    payload = response.json()
    assert payload["status"] == "ACTION_REQUIRED"
    assert payload["member_action_required"]["code"] == "PATIENT_MISMATCH"
    assert "Meera Deshpande" in payload["reason"]
    assert "EMP001" in payload["reason"]


def test_get_member_ytd_uses_claim_history(monkeypatch) -> None:
    client = TestClient(app)

    class FakeScalarResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class FakeExecuteResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return FakeScalarResult(self._rows)

    class FakeSession:
        def __init__(self, rows):
            self._rows = rows

        def execute(self, stmt):
            return FakeExecuteResult(self._rows)

        def close(self):
            pass

    rows = [
        SimpleNamespace(claim_id="CLM_1", claimed_amount=1200),
        SimpleNamespace(claim_id="CLM_2", claimed_amount=800),
    ]
    monkeypatch.setattr(claims_api, "SessionLocal", lambda: FakeSession(rows))

    response = client.get("/claims/members/EMP001/ytd", params={"as_of_date": "2024-11-01"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["member_id"] == "EMP001"
    assert payload["ytd_claims_amount"] == 2000
    assert payload["claim_count"] == 2
    assert payload["claim_ids"] == ["CLM_1", "CLM_2"]


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
    assert {item["component"] for item in payload["trace"]} >= {
        "DocumentVerifierAgent",
        "VisionExtractionAgent",
        "StructuredNormalizationAgent",
        "PatientConsistencyAgent",
    }
    assert payload["extracted_document_data"][0]["fields"]["diagnosis"] == "Viral Fever"


def test_completed_claim_includes_confidence_and_decision_explainability_trace() -> None:
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
                    "file_id": "F007",
                    "actual_type": "PRESCRIPTION",
                    "quality": "GOOD",
                    "content": {"patient_name": "Rajesh Kumar", "diagnosis": "Viral Fever"},
                },
                {
                    "file_id": "F008",
                    "actual_type": "HOSPITAL_BILL",
                    "quality": "GOOD",
                    "content": {"patient_name": "Rajesh Kumar", "total": 1500},
                },
            ],
        },
    )

    payload = response.json()
    confidence_trace = next(item for item in payload["trace"] if item["component"] == "ConfidenceScorer")
    explanation_trace = next(item for item in payload["trace"] if item["component"] == "DecisionExplainer")

    assert confidence_trace["checks_performed"] == [
        "document_quality",
        "extraction_completeness",
        "patient_consistency",
        "policy_evidence_strength",
        "rule_certainty",
        "component_failures",
    ]
    assert confidence_trace["output_summary"]["confidence_score"] == payload["confidence_score"]
    assert explanation_trace["input_summary"]["documents_checked"][0]["file_id"] == "F007"
    assert explanation_trace["input_summary"]["extracted_fields"][0]["fields"] == [
        "diagnosis",
        "patient_name",
    ]
    assert explanation_trace["output_summary"]["amount_calculation"]["approved_amount"] == 1350
    assert explanation_trace["evidence_ids"]


def test_extraction_pipeline_stops_for_normalized_patient_mismatch() -> None:
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
                    "file_id": "F051",
                    "file_name": "prescription.jpg",
                    "actual_type": "PRESCRIPTION",
                    "content": {"patientName": "Rajesh Kumar", "diagnosis": "Viral Fever"},
                },
                {
                    "file_id": "F052",
                    "file_name": "hospital_bill.jpg",
                    "actual_type": "HOSPITAL_BILL",
                    "content": {"patientName": "Arjun Mehta", "amount": "1500"},
                },
            ],
        },
    )

    payload = response.json()
    assert payload["status"] == "ACTION_REQUIRED"
    assert payload["decision"] is None
    assert payload["member_action_required"]["code"] == "PATIENT_MISMATCH"
    assert payload["extracted_document_data"][0]["fields"]["patient_name"] == "Rajesh Kumar"
    assert "Extracted patient names are inconsistent" in payload["reason"]


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


def test_submit_claim_stops_for_conflicting_patient_names() -> None:
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
    assert payload["status"] == "ACTION_REQUIRED"
    assert payload["decision"] is None
    assert payload["member_action_required"]["code"] == "PATIENT_MISMATCH"
    assert "Arjun Mehta" in payload["reason"]
    assert "Rajesh Kumar" in payload["reason"]


def test_submit_claim_stops_for_unknown_document_type() -> None:
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
                    "file_id": "F099",
                    "file_name": "random_attachment.jpg",
                    "quality": "GOOD",
                }
            ],
        },
    )

    payload = response.json()
    assert payload["status"] == "ACTION_REQUIRED"
    assert payload["member_action_required"]["code"] == "WRONG_DOCUMENT_TYPE"
    assert "could not be classified" in payload["reason"]


def test_submit_upload_classifies_files_with_backend_fallback() -> None:
    client = TestClient(app)

    response = client.post(
        "/claims/submit/upload",
        data={
            "member_id": "EMP001",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-11-01",
            "claimed_amount": "1500",
        },
        files=[
            ("files", ("prescription.jpg", b"prescription bytes", "image/jpeg")),
            ("files", ("hospital_bill.pdf", b"%PDF-1.4", "application/pdf")),
        ],
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["status"] == "COMPLETED"
    assert payload["decision"]["decision"] == "APPROVED"
    classifications = payload["trace"][1]["output_summary"]["classifications"]
    assert {item["document_type"] for item in classifications} == {"PRESCRIPTION", "HOSPITAL_BILL"}


def test_submit_upload_passes_uploaded_payload_to_extraction(monkeypatch) -> None:
    client = TestClient(app)
    seen_payloads: list[str] = []

    monkeypatch.setattr(extraction_pipeline.settings, "groq_api_key", "test-key")

    def fake_extract(document_type, content_base64, content_type):
        seen_payloads.append(base64.b64decode(content_base64).decode("utf-8"))
        fields = {"patient_name": "Rajesh Kumar"}
        if document_type == "PRESCRIPTION":
            fields["diagnosis"] = "Viral Fever"
        if document_type == "HOSPITAL_BILL":
            fields["total"] = 1500
        return SimpleNamespace(fields=fields, missing_fields=[], confidence=0.94, warnings=[])

    monkeypatch.setattr(extraction_pipeline, "_request_groq_extraction", fake_extract)

    response = client.post(
        "/claims/submit/upload",
        data={
            "member_id": "EMP001",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-11-01",
            "claimed_amount": "1500",
        },
        files=[
            ("files", ("prescription.jpg", b"prescription payload", "image/jpeg")),
            ("files", ("hospital_bill.jpg", b"bill payload", "image/jpeg")),
        ],
    )

    payload = response.json()
    assert response.status_code == 202
    assert seen_payloads == ["prescription payload", "bill payload"]
    assert payload["status"] == "COMPLETED"
    assert payload["component_failures"] == []
    assert payload["extracted_document_data"][0]["fields"]["diagnosis"] == "Viral Fever"
    assert payload["extracted_document_data"][1]["fields"]["total"] == 1500
    assert "base64" not in payload["submission"]["documents"][0]["content"]["upload"]


def test_llm_extraction_accepts_markdown_wrapped_json() -> None:
    payload = extraction_pipeline._parse_llm_extraction_payload(
        """Here is the valid JSON:
```json
{
  "fields": {
    "patient_name": "Meera Deshpande",
    "total": 231.8,
    "invoice_date": "2024-11-03"
  },
  "missing_fields": [],
  "confidence": 0.91,
  "warnings": []
}
```"""
    )

    assert payload.fields["patient_name"] == "Meera Deshpande"
    assert payload.fields["total"] == 231.8
    assert payload.confidence == 0.91


def test_line_item_normalization_preserves_pharmacy_item_names() -> None:
    item = extraction_pipeline._normalize_line_item({"medicine_name": "Amlodipine 5mg", "amount": "75.00"})

    assert item == {"description": "Amlodipine 5mg", "amount": 75.0}


def test_submit_upload_parses_text_from_pdf_documents() -> None:
    client = TestClient(app)

    prescription_pdf = _pdf_bytes(
        [
            "Dr. Arun Sharma, MBBS",
            "Patient: Rajesh Kumar    Date: 01-Nov-2024",
            "Diagnosis: Viral Fever",
            "Investigations: CBC, Dengue NS1",
        ]
    )
    hospital_bill_pdf = _pdf_bytes(
        [
            "CITY MEDICAL CENTRE",
            "Patient Name: Rajesh Kumar",
            "Consultation Fee (OPD)        1    1000.00  1000.00",
            "CBC (Complete Blood Count)    1     200.00   200.00",
            "Total Amount: 1200.00",
        ]
    )

    response = client.post(
        "/claims/submit/upload",
        data={
            "member_id": "EMP001",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "CONSULTATION",
            "treatment_date": "2024-11-01",
            "claimed_amount": "1200",
        },
        files=[
            ("files", ("prescription.pdf", prescription_pdf, "application/pdf")),
            ("files", ("hospital_bill.pdf", hospital_bill_pdf, "application/pdf")),
        ],
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["status"] == "COMPLETED"
    assert payload["decision"]["decision"] == "APPROVED"
    extracted = {item["file_id"]: item for item in payload["extracted_document_data"]}
    assert extracted["UPL001"]["fields"]["patient_name"] == "Rajesh Kumar"
    assert extracted["UPL001"]["fields"]["diagnosis"] == "Viral Fever"
    assert extracted["UPL002"]["fields"]["patient_name"] == "Rajesh Kumar"
    assert extracted["UPL002"]["fields"]["total"] == 1200


def test_parse_upload_returns_extracted_document_data() -> None:
    client = TestClient(app)

    prescription_pdf = _pdf_bytes(
        [
            "CITY CLINIC",
            "Patient: Rajesh Kumar",
            "Date: 01-Nov-2024",
            "Diagnosis: Viral Fever",
        ]
    )

    response = client.post(
        "/claims/parse/upload",
        files=[("files", ("prescription.pdf", prescription_pdf, "application/pdf"))],
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["confidence_impact"] <= 0
    assert payload["component_failures"] == []
    assert payload["extracted_documents"][0]["document_type"] == "PRESCRIPTION"
    assert payload["extracted_documents"][0]["fields"]["patient_name"] == "Rajesh Kumar"
    assert payload["extracted_documents"][0]["fields"]["diagnosis"] == "Viral Fever"
    assert payload["extracted_documents"][0]["fields"]["invoice_date"] == "2024-11-01"


def test_parse_upload_extracts_bill_total_from_line_items() -> None:
    client = TestClient(app)

    hospital_bill_pdf = _pdf_bytes(
        [
            "CITY MEDICAL CENTRE",
            "Patient Name: Rajesh Kumar",
            "Consultation Fee (OPD)        1    1000.00  1000.00",
            "CBC (Complete Blood Count)    1     200.00   200.00",
        ]
    )

    response = client.post(
        "/claims/parse/upload",
        files=[("files", ("hospital_bill.pdf", hospital_bill_pdf, "application/pdf"))],
    )

    payload = response.json()
    assert response.status_code == 200
    extracted = payload["extracted_documents"][0]["fields"]
    assert extracted["patient_name"] == "Rajesh Kumar"
    assert extracted["total"] == 1200
    assert len(extracted["line_items"]) == 2


def test_parse_upload_does_not_infer_total_from_lab_ranges() -> None:
    client = TestClient(app)

    lab_report_pdf = _pdf_bytes(
        [
            "ABC Diagnostics",
            "Patient Name: Rajesh Kumar",
            "Hemoglobin 13.5 g/dL 12.0 - 16.0",
            "WBC Count 6800 cells/uL 4000 - 11000",
            "Platelets 2.10 lakh/uL 1.50 - 4.50",
            "Diagnosis: Routine checkup",
        ]
    )

    response = client.post(
        "/claims/parse/upload",
        files=[("files", ("lab_report.pdf", lab_report_pdf, "application/pdf"))],
    )

    payload = response.json()
    assert response.status_code == 200
    extracted = payload["extracted_documents"][0]["fields"]
    assert extracted["patient_name"] == "Rajesh Kumar"
    assert extracted["diagnosis"] == "Routine checkup"
    assert "total" not in extracted
    assert "line_items" not in extracted


def test_submit_upload_stops_for_unreadable_file() -> None:
    client = TestClient(app)

    response = client.post(
        "/claims/submit/upload",
        data={
            "member_id": "EMP004",
            "policy_id": "PLUM_GHI_2024",
            "claim_category": "PHARMACY",
            "treatment_date": "2024-10-25",
            "claimed_amount": "800",
        },
        files=[
            ("files", ("prescription.jpg", b"prescription bytes", "image/jpeg")),
            ("files", ("blurry_bill.jpg", b"", "image/jpeg")),
        ],
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["status"] == "ACTION_REQUIRED"
    assert payload["decision"] is None
    assert payload["member_action_required"]["code"] == "UNREADABLE_DOCUMENT"
    assert "blurry_bill.jpg" in payload["reason"]
