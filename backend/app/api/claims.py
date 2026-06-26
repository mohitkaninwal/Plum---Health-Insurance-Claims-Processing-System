from fastapi import APIRouter, HTTPException, status

from app.models import ClaimResponse, ClaimStatus, ClaimSubmission, TraceEvent

router = APIRouter(prefix="/claims", tags=["claims"])

_CLAIMS: dict[str, ClaimResponse] = {}


@router.post(
    "/submit",
    response_model=ClaimResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Accept a claim submission",
)
async def submit_claim(submission: ClaimSubmission) -> ClaimResponse:
    response = ClaimResponse(
        status=ClaimStatus.RECEIVED,
        submission=submission,
        trace=[
            TraceEvent(
                component="ClaimIntakeAPI",
                message="Claim submission accepted. Processing pipeline is not attached yet.",
                input_summary={
                    "member_id": submission.member_id,
                    "policy_id": submission.policy_id,
                    "claim_category": submission.claim_category,
                    "claimed_amount": submission.claimed_amount,
                    "document_count": len(submission.documents),
                },
                output_summary={"status": ClaimStatus.RECEIVED},
            )
        ],
    )
    _CLAIMS[response.claim_id] = response
    return response


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

