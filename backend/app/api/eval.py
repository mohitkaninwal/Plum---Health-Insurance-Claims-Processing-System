import asyncio

from fastapi import APIRouter, Request

from app.models import ClaimStatus, EvalMetrics, EvalRun
from app.services.claims_processor import run_test_case_eval

router = APIRouter(prefix="/eval", tags=["eval"])

_LATEST_EVAL_RUN: EvalRun | None = None


@router.post(
    "/run",
    response_model=EvalRun,
    summary="Create an eval run shell for the 12 assignment cases",
)
async def run_eval(request: Request) -> EvalRun:
    global _LATEST_EVAL_RUN

    policy = getattr(request.app.state, "policy_terms", None)
    _LATEST_EVAL_RUN = await asyncio.to_thread(run_test_case_eval, policy=policy)
    return _LATEST_EVAL_RUN


@router.get(
    "/latest",
    response_model=EvalRun,
    summary="Fetch the latest eval run",
)
async def get_latest_eval() -> EvalRun:
    if _LATEST_EVAL_RUN is not None:
        return _LATEST_EVAL_RUN

    return EvalRun(
        status=ClaimStatus.RECEIVED,
        metrics=EvalMetrics(total_cases=12),
        cases=[],
    )
