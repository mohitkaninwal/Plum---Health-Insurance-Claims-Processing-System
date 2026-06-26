from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.contracts import ClaimCategory, DocumentType


class StrictPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PolicyHolder(StrictPolicyModel):
    company_name: str
    employee_count: int = Field(gt=0)
    policy_start_date: date
    policy_end_date: date
    renewal_status: str


class FamilyFloater(StrictPolicyModel):
    enabled: bool
    combined_limit: float = Field(ge=0)
    covered_relationships: list[str]


class Coverage(StrictPolicyModel):
    sum_insured_per_employee: float = Field(gt=0)
    annual_opd_limit: float = Field(ge=0)
    per_claim_limit: float = Field(ge=0)
    family_floater: FamilyFloater


class OpdCategoryConfig(StrictPolicyModel):
    sub_limit: float = Field(ge=0)
    copay_percent: float = Field(ge=0, le=100)
    network_discount_percent: float | None = Field(default=None, ge=0, le=100)
    branded_drug_copay_percent: float | None = Field(default=None, ge=0, le=100)
    generic_mandatory: bool | None = None
    requires_prescription: bool
    requires_pre_auth: bool | None = None
    pre_auth_threshold: float | None = Field(default=None, ge=0)
    high_value_tests_requiring_pre_auth: list[str] | None = None
    requires_dental_report: bool | None = None
    covered_procedures: list[str] | None = None
    excluded_procedures: list[str] | None = None
    covered_items: list[str] | None = None
    excluded_items: list[str] | None = None
    requires_registered_practitioner: bool | None = None
    max_sessions_per_year: int | None = Field(default=None, ge=0)
    covered_systems: list[str] | None = None
    covered: bool


class WaitingPeriods(StrictPolicyModel):
    initial_waiting_period_days: int = Field(ge=0)
    pre_existing_conditions_days: int = Field(ge=0)
    specific_conditions: dict[str, int]


class Exclusions(StrictPolicyModel):
    conditions: list[str]
    dental_exclusions: list[str]
    vision_exclusions: list[str]


class PreAuthorization(StrictPolicyModel):
    required_for: list[str]
    validity_days: int = Field(gt=0)


class SubmissionRules(StrictPolicyModel):
    deadline_days_from_treatment: int = Field(ge=0)
    minimum_claim_amount: float = Field(ge=0)
    currency: str


class DocumentRequirement(StrictPolicyModel):
    required: list[DocumentType]
    optional: list[DocumentType]


class FraudThresholds(StrictPolicyModel):
    same_day_claims_limit: int = Field(ge=0)
    monthly_claims_limit: int = Field(ge=0)
    high_value_claim_threshold: float = Field(ge=0)
    auto_manual_review_above: float = Field(ge=0)
    fraud_score_manual_review_threshold: float = Field(ge=0, le=1)


class PolicyMember(StrictPolicyModel):
    member_id: str
    name: str
    date_of_birth: date
    gender: str
    relationship: str
    join_date: date | None = None
    dependents: list[str] = Field(default_factory=list)
    primary_member_id: str | None = None


class PolicyTerms(StrictPolicyModel):
    policy_id: str
    policy_name: str
    insurer: str
    policy_holder: PolicyHolder
    coverage: Coverage
    opd_categories: dict[str, OpdCategoryConfig]
    waiting_periods: WaitingPeriods
    exclusions: Exclusions
    pre_authorization: PreAuthorization
    network_hospitals: list[str]
    submission_rules: SubmissionRules
    document_requirements: dict[ClaimCategory, DocumentRequirement]
    fraud_thresholds: FraudThresholds
    members: list[PolicyMember]

    def as_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
