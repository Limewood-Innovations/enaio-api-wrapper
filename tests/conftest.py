"""Pytest fixtures for enaio_api_wrapper tests."""

from __future__ import annotations

import pytest
import pytest_asyncio

from enaio_api_wrapper import AsyncEnaioClient


@pytest_asyncio.fixture
async def client() -> AsyncEnaioClient:
    """An AsyncEnaioClient pointed at a test host. Caller is responsible for
    using ``async with`` or registering aresponses."""
    async with AsyncEnaioClient(
        host="http://test.invalid/",
        api_url_base="osrest/api/",
        rendition_cache_url_base="osrenditioncache/app/api/",
        username="u",
        password="p",
        # No CA file → uses default trust store. aresponses intercepts before TLS.
        timeout=5.0,
    ) as c:
        yield c


@pytest.fixture
def host() -> str:
    return "test.invalid"
