from fastapi import APIRouter, HTTPException, Request, status

from app.models import ClaimResponse, ClaimSubmission
from app.services.claims_processor import process_claim

router = APIRouter(prefix="/claims", tags=["claims"])

_CLAIMS: dict[str, ClaimResponse] = {}


@router.post(
    "/submit",
    response_model=ClaimResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Accept a claim submission",
)
async def submit_claim(request: Request, submission: ClaimSubmission) -> ClaimResponse:
    policy = getattr(request.app.state, "policy_terms", None)
    response = process_claim(submission, policy=policy)
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
