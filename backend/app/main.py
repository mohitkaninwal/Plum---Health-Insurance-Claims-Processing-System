from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.claims import router as claims_router
from app.api.eval import router as eval_router
from app.api.health import router as health_router
from app.core.config import settings
from app.services.policy_loader import load_policy_terms_on_startup

# ── Structured JSON logging ───────────────────────────────────────────────────

try:
    from pythonjsonlogger import jsonlogger  # type: ignore[import-untyped]

    _handler = logging.StreamHandler()
    _handler.setFormatter(
        jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    logging.root.handlers = [_handler]
except ImportError:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s %(message)s")

log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
logging.root.setLevel(log_level)

# ── Request-ID context variable ───────────────────────────────────────────────

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.policy_terms = load_policy_terms_on_startup()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Explainable health insurance claims processing API.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: object) -> Response:
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_var.set(rid)
        try:
            response: Response = await call_next(request)  # type: ignore[operator]
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            request_id_var.reset(token)

    app.include_router(health_router)
    app.include_router(claims_router)
    app.include_router(eval_router)
    return app


app = create_app()
