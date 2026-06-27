from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from datetime import date
from sqlalchemy import select

from app.db.models import ClaimIntakeRecord
from app.db.session import SessionLocal
from app.models import (
    ClaimResponse,
    ClaimSubmission,
    DocumentParseResult,
    MemberYtdSummary,
    PolicyContext,
    PolicyMemberSummary,
)
from app.services.claim_intake_repository import persist_claim_intake
from app.services.claims_processor import process_claim
from app.services.extraction_pipeline import run_extraction_pipeline
from app.services.document_intake import (
    ParseDocumentForm,
    UploadDocumentForm,
    response_without_upload_payloads,
    submission_from_parse_form,
    submission_from_upload_form,
)
from app.services.policy_loader import read_policy_terms

router = APIRouter(prefix="/claims", tags=["claims"])

_CLAIMS: dict[str, ClaimResponse] = {}


@router.get(
    "/context",
    response_model=PolicyContext,
    status_code=status.HTTP_200_OK,
    summary="Return the active policy and member roster",
)
async def get_claim_context(request: Request) -> PolicyContext:
    policy = getattr(request.app.state, "policy_terms", None) or read_policy_terms()
    member_ids = {member.member_id for member in policy.members}
    unresolved_dependents = sorted(
        {
            dependent_id
            for member in policy.members
            for dependent_id in member.dependents
            if dependent_id not in member_ids
        }
    )

    return PolicyContext(
        policy_id=policy.policy_id,
        policy_name=policy.policy_name,
        insurer=policy.insurer,
        company_name=policy.policy_holder.company_name,
        members=[
            PolicyMemberSummary(
                member_id=member.member_id,
                name=member.name,
                relationship=member.relationship,
                join_date=member.join_date,
                primary_member_id=member.primary_member_id,
                dependents=member.dependents,
            )
            for member in policy.members
        ],
        unresolved_dependent_ids=unresolved_dependents,
    )


@router.get(
    "/members/{member_id}/ytd",
    response_model=MemberYtdSummary,
    status_code=status.HTTP_200_OK,
    summary="Return year-to-date claim usage for a member",
)
async def get_member_ytd(member_id: str, request: Request, as_of_date: str | None = None) -> MemberYtdSummary:
    policy = getattr(request.app.state, "policy_terms", None) or read_policy_terms()

    member = next((item for item in policy.members if item.member_id == member_id), None)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Member '{member_id}' was not found.")

    summary = _member_ytd_summary(member_id, policy.policy_id, policy.policy_holder.policy_start_date, as_of_date)
    return summary


@router.post(
    "/submit",
    response_model=ClaimResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Accept a claim submission",
)
async def submit_claim(request: Request, submission: ClaimSubmission) -> ClaimResponse:
    policy = getattr(request.app.state, "policy_terms", None)
    response = process_claim(submission, policy=policy)
    response = persist_claim_intake(response)
    _CLAIMS[response.claim_id] = response
    return response


@router.post(
    "/submit/upload",
    response_model=ClaimResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Accept a claim submission with real uploaded documents",
)
async def submit_claim_upload(
    request: Request, form: Annotated[UploadDocumentForm, Depends()]
) -> ClaimResponse:
    policy = getattr(request.app.state, "policy_terms", None)
    submission = await submission_from_upload_form(form)
    response = process_claim(submission, policy=policy)
    response = response_without_upload_payloads(response)
    response = persist_claim_intake(response)
    _CLAIMS[response.claim_id] = response
    return response


@router.post(
    "/parse/upload",
    response_model=DocumentParseResult,
    status_code=status.HTTP_200_OK,
    summary="Parse uploaded documents without adjudicating the claim",
)
async def parse_claim_upload(
    form: Annotated[ParseDocumentForm, Depends()]
) -> DocumentParseResult:
    submission = await submission_from_parse_form(form)
    parsed = run_extraction_pipeline(submission)
    return DocumentParseResult(
        extracted_documents=parsed.extracted_documents,
        trace=parsed.trace,
        component_failures=parsed.component_failures,
        member_action_required=parsed.member_action_required,
        confidence_impact=parsed.confidence_impact,
    )


def _member_ytd_summary(
    member_id: str,
    policy_id: str,
    policy_start_date: date,
    as_of_date: str | None = None,
) -> MemberYtdSummary:
    if SessionLocal is None:
        return MemberYtdSummary(
            policy_id=policy_id,
            member_id=member_id,
            as_of_date=_parse_as_of_date(as_of_date),
            ytd_claims_amount=0,
            claim_count=0,
            claim_ids=[],
        )

    db = SessionLocal()
    try:
        cutoff = _parse_as_of_date(as_of_date)
        start_of_period = policy_start_date
        stmt = (
            select(ClaimIntakeRecord)
            .where(ClaimIntakeRecord.policy_id == policy_id)
            .where(ClaimIntakeRecord.member_id == member_id)
            .where(ClaimIntakeRecord.treatment_date >= start_of_period)
            .where(ClaimIntakeRecord.treatment_date <= cutoff)
        )
        rows = list(db.execute(stmt).scalars().all())
        claim_ids = [row.claim_id for row in rows]
        total = float(sum(float(row.claimed_amount or 0) for row in rows))
        return MemberYtdSummary(
            policy_id=policy_id,
            member_id=member_id,
            as_of_date=cutoff,
            ytd_claims_amount=total,
            claim_count=len(rows),
            claim_ids=claim_ids,
        )
    finally:
        db.close()


def _parse_as_of_date(value: str | None) -> date:
    from datetime import datetime

    if not value:
        return date.today()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return date.fromisoformat(value)


@router.get(
    "/{claim_id}",
    response_model=ClaimResponse,
    summary="Fetch a claim response and trace by claim ID",
)
async def get_claim(claim_id: str) -> ClaimResponse:
    claim = _CLAIMS.get(claim_id)
    if claim is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim '{claim_id}' was not found.",
        )
    return claim
