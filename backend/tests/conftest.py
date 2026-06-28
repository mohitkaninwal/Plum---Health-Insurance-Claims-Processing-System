"""Shared pytest fixtures for the Plum Claims API test suite."""
from __future__ import annotations

import pytest

from app.services import extraction_pipeline


@pytest.fixture(autouse=True)
def clear_extraction_cache() -> None:
    """Clear the LRU extraction cache before and after every test.

    The cache is a module-level OrderedDict that persists across tests in the
    same process.  Without this fixture a test that triggers Groq extraction
    could silently satisfy a later test's assertions via a stale cache hit,
    masking real extraction failures.
    """
    with extraction_pipeline._CACHE_LOCK:
        extraction_pipeline._EXTRACTION_CACHE.clear()
    yield
    with extraction_pipeline._CACHE_LOCK:
        extraction_pipeline._EXTRACTION_CACHE.clear()
