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

# JPEG SOI marker — used as opaque body in download_thumbnail tests
_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF"
# PDF magic header — opaque body in download_pdf tests
_PDF_BYTES = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3"


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


# --- download_pdf -----------------------------------------------------------
#
# Regression tests for the bug where ``download_pdf`` was issuing
# ``GET .../rendition/pdf/`` (trailing slash, no ``?timeout=``) instead of
# the v2 production shape ``GET .../rendition/pdf?timeout=30000``. Without
# the timeout hint Enaio's rendition cache 404s immediately on cache-miss
# with ``cause=cannot find resource for digest [...#pdf]`` instead of
# triggering / awaiting the renderer. download_thumbnail had this
# parameter from the start of v3; download_pdf regressed.


async def test_download_pdf_returns_bytes(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    aresponses.add(
        "test.invalid",
        "/osrenditioncache/app/api/document/42/rendition/pdf",
        "GET",
        aresponses.Response(status=200, body=_PDF_BYTES),
    )
    blob = await client.download_pdf(42)
    assert blob == _PDF_BYTES


async def test_download_pdf_url_has_no_trailing_slash(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    """Regression: v3.3.0 hit ``.../rendition/pdf/`` (trailing slash) which
    some Java servlet containers route as a distinct path. v2 production
    URL ended at ``.../rendition/pdf`` with no slash — restore that."""
    seen_paths: list[str] = []

    async def handler(request):
        seen_paths.append(request.path)
        return aresponses.Response(status=200, body=_PDF_BYTES)

    aresponses.add(
        "test.invalid",
        "/osrenditioncache/app/api/document/42/rendition/pdf",
        "GET",
        handler,
    )
    await client.download_pdf(42)
    assert seen_paths, "handler never fired — request did not match path"
    assert all(not p.endswith("/rendition/pdf/") for p in seen_paths), (
        f"PDF URL must not end with trailing slash; saw {seen_paths!r}"
    )


async def test_download_pdf_sends_default_30s_timeout_query(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    """Regression: v3.3.0 dropped ``?timeout=N`` entirely. Without it
    Enaio's rendition cache returns 404 on cache-miss instead of
    triggering / awaiting the renderer. 30000 ms matches the v2 client's
    pinned production value."""
    captured: dict[str, str] = {}

    async def handler(request):
        captured.update(request.query)
        return aresponses.Response(status=200, body=_PDF_BYTES)

    aresponses.add(
        "test.invalid",
        "/osrenditioncache/app/api/document/42/rendition/pdf",
        "GET",
        handler,
    )
    await client.download_pdf(42)
    assert captured.get("timeout") == "30000"


async def test_download_pdf_custom_timeout_query(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    captured: dict[str, str] = {}

    async def handler(request):
        captured.update(request.query)
        return aresponses.Response(status=200, body=_PDF_BYTES)

    aresponses.add(
        "test.invalid",
        "/osrenditioncache/app/api/document/42/rendition/pdf",
        "GET",
        handler,
    )
    await client.download_pdf(42, timeout_ms=60000)
    assert captured.get("timeout") == "60000"


async def test_download_pdf_rejects_non_positive_timeout(
    client: AsyncEnaioClient,
) -> None:
    with pytest.raises(EnaioConfigError):
        await client.download_pdf(42, timeout_ms=0)
    with pytest.raises(EnaioConfigError):
        await client.download_pdf(42, timeout_ms=-1)


async def test_download_pdf_requires_rendition_cache_url() -> None:
    async with AsyncEnaioClient(
        host="http://test.invalid/",
        api_url_base="osrest/api/",
        username="u",
        password="p",
        timeout=5.0,
    ) as c:
        with pytest.raises(EnaioConfigError):
            await c.download_pdf(42)


async def test_download_pdf_propagates_404(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    aresponses.add(
        "test.invalid",
        "/osrenditioncache/app/api/document/9/rendition/pdf",
        "GET",
        aresponses.Response(status=404, text="missing"),
    )
    with pytest.raises(EnaioNotFoundError):
        await client.download_pdf(9)


# --- download_thumbnail -----------------------------------------------------


async def test_download_thumbnail_returns_bytes(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    aresponses.add(
        "test.invalid",
        "/osrenditioncache/app/api/document/42/rendition/thumbnail/1200",
        "GET",
        aresponses.Response(status=200, body=_JPEG_BYTES),
    )
    blob = await client.download_thumbnail(42)
    assert blob == _JPEG_BYTES


async def test_download_thumbnail_custom_size_in_path(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    aresponses.add(
        "test.invalid",
        "/osrenditioncache/app/api/document/42/rendition/thumbnail/800",
        "GET",
        aresponses.Response(status=200, body=_JPEG_BYTES),
    )
    blob = await client.download_thumbnail(42, size=800)
    assert blob == _JPEG_BYTES


async def test_download_thumbnail_sends_default_12s_timeout_query(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    # The ?timeout=12000 server-side rendering hint is critical — Enaio uses
    # it to decide how long to wait for the rendition to materialise. Mirrors
    # the value v2 production pinned at commit 9ed8179.
    captured: dict[str, str] = {}

    async def handler(request):
        captured.update(request.query)
        return aresponses.Response(status=200, body=_JPEG_BYTES)

    aresponses.add(
        "test.invalid",
        "/osrenditioncache/app/api/document/42/rendition/thumbnail/1200",
        "GET",
        handler,
    )
    await client.download_thumbnail(42)
    assert captured.get("timeout") == "12000"


async def test_download_thumbnail_custom_timeout_query(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    captured: dict[str, str] = {}

    async def handler(request):
        captured.update(request.query)
        return aresponses.Response(status=200, body=_JPEG_BYTES)

    aresponses.add(
        "test.invalid",
        "/osrenditioncache/app/api/document/42/rendition/thumbnail/1200",
        "GET",
        handler,
    )
    await client.download_thumbnail(42, timeout_ms=30000)
    assert captured.get("timeout") == "30000"


async def test_download_thumbnail_rejects_non_positive_size(
    client: AsyncEnaioClient,
) -> None:
    with pytest.raises(EnaioConfigError):
        await client.download_thumbnail(42, size=0)
    with pytest.raises(EnaioConfigError):
        await client.download_thumbnail(42, size=-1)


async def test_download_thumbnail_rejects_non_positive_timeout(
    client: AsyncEnaioClient,
) -> None:
    with pytest.raises(EnaioConfigError):
        await client.download_thumbnail(42, timeout_ms=0)
    with pytest.raises(EnaioConfigError):
        await client.download_thumbnail(42, timeout_ms=-1)


async def test_download_thumbnail_requires_rendition_cache_url() -> None:
    # Construct a client without rendition_cache_url_base and confirm the
    # missing-config error surfaces (matches download_pdf's behaviour).
    async with AsyncEnaioClient(
        host="http://test.invalid/",
        api_url_base="osrest/api/",
        username="u",
        password="p",
        timeout=5.0,
    ) as c:
        with pytest.raises(EnaioConfigError):
            await c.download_thumbnail(42)


async def test_download_thumbnail_propagates_404(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    aresponses.add(
        "test.invalid",
        "/osrenditioncache/app/api/document/9/rendition/thumbnail/1200",
        "GET",
        aresponses.Response(status=404, text="missing"),
    )
    with pytest.raises(EnaioNotFoundError):
        await client.download_thumbnail(9)


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
