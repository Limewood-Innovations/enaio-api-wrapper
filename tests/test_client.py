"""Smoke tests for AsyncEnaioClient using aresponses (no live HTTP)."""

from __future__ import annotations

import json

import pytest
from aresponses import ResponsesMockServer

from enaio_api_wrapper import (
    AsyncEnaioClient,
    EnaioAuthError,
    EnaioConfigError,
    EnaioHTTPError,
    EnaioNotFoundError,
)


async def test_serviceinfo_ok(aresponses: ResponsesMockServer, client: AsyncEnaioClient) -> None:
    aresponses.add(
        "test.invalid",
        "/osrest/api/serviceinfo",
        "GET",
        aresponses.Response(status=200, text=json.dumps({"apiVersion": "9.0"})),
    )
    info = await client.serviceinfo()
    assert info == {"apiVersion": "9.0"}


async def test_auth_error_raises(aresponses: ResponsesMockServer, client: AsyncEnaioClient) -> None:
    aresponses.add(
        "test.invalid",
        "/osrest/api/serviceinfo",
        "GET",
        aresponses.Response(status=401, text='{"error":"unauthorized"}'),
    )
    with pytest.raises(EnaioAuthError) as exc:
        await client.serviceinfo()
    assert exc.value.status == 401


async def test_check_osid_exists_true(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    aresponses.add(
        "test.invalid",
        "/osrest/api/documents/search/12345",
        "GET",
        aresponses.Response(status=200, text='{"osid":"12345"}'),
    )
    assert await client.check_osid_exists(12345) is True


async def test_check_osid_exists_false_on_404(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    aresponses.add(
        "test.invalid",
        "/osrest/api/documents/search/9",
        "GET",
        aresponses.Response(status=404, text='{"error":"not found"}'),
    )
    assert await client.check_osid_exists(9) is False


async def test_check_osid_exists_propagates_5xx(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    aresponses.add(
        "test.invalid",
        "/osrest/api/documents/search/9",
        "GET",
        aresponses.Response(status=500, text="boom"),
    )
    with pytest.raises(EnaioHTTPError) as exc:
        await client.check_osid_exists(9)
    assert exc.value.status == 500


async def test_get_object_returns_none_on_404(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    aresponses.add(
        "test.invalid",
        "/osrest/api/documents/search/9/",
        "GET",
        aresponses.Response(status=404, text='{"error":"not found"}'),
    )
    assert await client.get_object(9) is None


def test_construct_requires_host() -> None:
    with pytest.raises(EnaioConfigError):
        AsyncEnaioClient(host="", api_url_base="osrest/api/", username="u", password="p")


def test_construct_requires_api_url_base() -> None:
    with pytest.raises(EnaioConfigError):
        AsyncEnaioClient(host="https://x/", api_url_base="", username="u", password="p")


async def test_call_without_async_with_raises() -> None:
    c = AsyncEnaioClient(
        host="https://x/", api_url_base="osrest/api/", username="u", password="p"
    )
    with pytest.raises(EnaioConfigError):
        await c.serviceinfo()


async def test_not_found_subclasses_http_error(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    aresponses.add(
        "test.invalid",
        "/osrest/api/serviceinfo",
        "GET",
        aresponses.Response(status=404, text="missing"),
    )
    with pytest.raises(EnaioNotFoundError):
        await client.serviceinfo()
    # also catchable as the parent class
    aresponses.add(
        "test.invalid",
        "/osrest/api/serviceinfo",
        "GET",
        aresponses.Response(status=404, text="missing"),
    )
    with pytest.raises(EnaioHTTPError):
        await client.serviceinfo()
