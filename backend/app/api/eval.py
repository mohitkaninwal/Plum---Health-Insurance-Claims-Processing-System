from fastapi import APIRouter

from app.models import ClaimStatus, EvalMetrics, EvalRun

router = APIRouter(prefix="/eval", tags=["eval"])

_LATEST_EVAL_RUN: EvalRun | None = None


@router.post(
    "/run",
    response_model=EvalRun,
    summary="Create an eval run shell for the 12 assignment cases",
)
async def run_eval() -> EvalRun:
    global _LATEST_EVAL_RUN

    _LATEST_EVAL_RUN = EvalRun(
        status=ClaimStatus.RECEIVED,
        metrics=EvalMetrics(total_cases=12),
        cases=[],
    )
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
