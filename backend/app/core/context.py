"""Shared async context variables.

Keeping these in a dedicated module prevents circular imports between
app/main.py (which sets values) and app/models/contracts.py (which reads them).
"""
from __future__ import annotations

from contextvars import ContextVar

# Set by the request-ID middleware in main.py; read by TraceEvent.model_post_init
# and any service that needs to correlate logs to an HTTP request.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
