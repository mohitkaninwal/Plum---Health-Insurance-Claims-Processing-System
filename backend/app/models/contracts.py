from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClaimCategory(StrEnum):
    CONSULTATION = "CONSULTATION"
    DIAGNOSTIC = "DIAGNOSTIC"
    PHARMACY = "PHARMACY"
    DENTAL = "DENTAL"
    VISION = "VISION"
    ALTERNATIVE_MEDICINE = "ALTERNATIVE_MEDICINE"


class DocumentType(StrEnum):
    PRESCRIPTION = "PRESCRIPTION"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    LAB_REPORT = "LAB_REPORT"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
    PHARMACY_BILL = "PHARMACY_BILL"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    DENTAL_REPORT = "DENTAL_REPORT"
    UNKNOWN = "UNKNOWN"


class DocumentQuality(StrEnum):
    GOOD = "GOOD"
    LOW = "LOW"
    UNREADABLE = "UNREADABLE"
    UNKNOWN = "UNKNOWN"


class ClaimStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ClaimDecisionType(StrEnum):
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class TraceLevel(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LineItemDecisionType(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ADJUSTED = "ADJUSTED"
    REVIEW = "REVIEW"


class ClaimHistoryItem(BaseModel):
    claim_id: str
    date: date
    amount: float = Field(ge=0)
    provider: str | None = None


class UploadedDocument(BaseModel):
    file_id: str
    file_name: str | None = None
    declared_type: DocumentType | None = None
    actual_type: DocumentType | None = Field(
        default=None,
        description="Fixture-only field used by the deterministic test-case adapter.",
    )
    quality: DocumentQuality | None = None
    patient_name_on_doc: str | None = None
    content: dict[str, Any] | None = None


class ClaimSubmission(BaseModel):
    member_id: str
    policy_id: str
    claim_category: ClaimCategory
    treatment_date: date
    claimed_amount: float = Field(gt=0)
    documents: list[UploadedDocument] = Field(min_length=1)
    ytd_claims_amount: float | None = Field(default=None, ge=0)
    hospital_name: str | None = None
    claims_history: list[ClaimHistoryItem] = Field(default_factory=list)
    simulate_component_failure: bool = False


class DocumentClassification(BaseModel):
    file_id: str
    document_type: DocumentType
    confidence: float = Field(ge=0, le=1)
    rationale: str | None = None


class ExtractedDocumentData(BaseModel):
    file_id: str
    document_type: DocumentType
    fields: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)


class DocumentParseResult(BaseModel):
    extracted_documents: list[ExtractedDocumentData] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)
    component_failures: list[ComponentFailure] = Field(default_factory=list)
    member_action_required: MemberActionRequired | None = None
    confidence_impact: float = 0


class PolicyEvidence(BaseModel):
    evidence_id: str
    source: str
    source_path: str | None = None
    rule_category: str
    claim_category: ClaimCategory | None = None
    text: str
    dense_score: float | None = None
    lexical_score: float | None = None
    rrf_score: float | None = None


class PolicyMemberSummary(BaseModel):
    member_id: str
    name: str
    relationship: str
    join_date: date | None = None
    primary_member_id: str | None = None
    dependents: list[str] = Field(default_factory=list)


class PolicyContext(BaseModel):
    policy_id: str
    policy_name: str
    insurer: str
    company_name: str
    members: list[PolicyMemberSummary] = Field(default_factory=list)
    unresolved_dependent_ids: list[str] = Field(default_factory=list)


class MemberYtdSummary(BaseModel):
    policy_id: str
    member_id: str
    as_of_date: date
    ytd_claims_amount: float
    claim_count: int
    claim_ids: list[str] = Field(default_factory=list)


class RuleCheckResult(BaseModel):
    rule_id: str
    rule_name: str
    passed: bool
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence_impact: float = 0


class LineItemDecision(BaseModel):
    description: str
    claimed_amount: float = Field(ge=0)
    approved_amount: float = Field(ge=0)
    decision: LineItemDecisionType
    reason: str

    @model_validator(mode="after")
    def approved_amount_cannot_exceed_claimed(self) -> "LineItemDecision":
        if self.approved_amount > self.claimed_amount:
            raise ValueError("approved_amount cannot exceed claimed_amount")
        return self


class MemberActionRequired(BaseModel):
    code: str
    message: str
    affected_file_ids: list[str] = Field(default_factory=list)
    required_document_types: list[DocumentType] = Field(default_factory=list)


class ComponentFailure(BaseModel):
    component: str
    message: str
    recoverable: bool = True


class TraceEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    component: str
    level: TraceLevel = TraceLevel.INFO
    message: str
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    checks_performed: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence_impact: float = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ClaimDecision(BaseModel):
    decision: ClaimDecisionType
    approved_amount: float = Field(ge=0)
    confidence_score: float = Field(ge=0, le=1)
    reason: str
    rejection_reasons: list[str] = Field(default_factory=list)
    line_item_decisions: list[LineItemDecision] = Field(default_factory=list)


class ClaimResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    claim_id: str = Field(default_factory=lambda: f"CLM_{uuid4().hex[:12].upper()}")
    status: ClaimStatus
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    submission: ClaimSubmission | None = None
    decision: ClaimDecision | None = None
    approved_amount: float | None = Field(default=None, ge=0)
    confidence_score: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = None
    rejection_reasons: list[str] = Field(default_factory=list)
    line_item_decisions: list[LineItemDecision] = Field(default_factory=list)
    extracted_document_data: list[ExtractedDocumentData] = Field(default_factory=list)
    member_action_required: MemberActionRequired | None = None
    trace: list[TraceEvent] = Field(default_factory=list)
    retrieved_policy_evidence: list[PolicyEvidence] = Field(default_factory=list)
    component_failures: list[ComponentFailure] = Field(default_factory=list)


class EvalCaseResult(BaseModel):
    case_id: str
    case_name: str
    passed: bool | None = None
    expected: dict[str, Any] = Field(default_factory=dict)
    actual: ClaimResponse | None = None
    notes: list[str] = Field(default_factory=list)


class EvalMetrics(BaseModel):
    total_cases: int = 0
    completed_cases: int = 0
    decision_accuracy: float | None = None
    early_stop_accuracy: float | None = None
    approved_amount_exact_match_rate: float | None = None
    system_must_accuracy: float | None = None


class EvalRun(BaseModel):
    eval_run_id: str = Field(default_factory=lambda: f"EVAL_{uuid4().hex[:12].upper()}")
    status: ClaimStatus
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    metrics: EvalMetrics = Field(default_factory=EvalMetrics)
    cases: list[EvalCaseResult] = Field(default_factory=list)
