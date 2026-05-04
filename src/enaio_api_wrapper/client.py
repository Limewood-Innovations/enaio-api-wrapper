"""Async HTTP client for the Enaio (OSREST) API.

This module provides :class:`AsyncEnaioClient` — a thin, typed wrapper around
:class:`aiohttp.ClientSession` with Basic-Auth, optional CA-cert verification,
and unified error handling.

The client can be used in two modes:

1. **Owned session** — most common::

       async with AsyncEnaioClient(...) as client:
           ...

   The client creates and owns the underlying ``aiohttp.ClientSession`` and
   closes it on ``__aexit__``.

2. **Borrowed session** — when the caller already has an ``aiohttp.ClientSession``
   (e.g. for connection pooling across services)::

       async with aiohttp.ClientSession(...) as session:
           client = AsyncEnaioClient.from_session(session, host=..., api_url_base=...)
           ...

   The caller is responsible for closing the session.
"""

from __future__ import annotations

import logging
import ssl
from types import TracebackType
from typing import Any, Mapping

import aiohttp
from yarl import URL

from .exceptions import (
    EnaioAuthError,
    EnaioConfigError,
    EnaioHTTPError,
    EnaioNotFoundError,
    EnaioResponseError,
)

_DEFAULT_TIMEOUT_SECONDS = 30.0


class AsyncEnaioClient:
    """Async client for the Enaio OSREST API.

    Args:
        host: Base host URL, e.g. ``https://alpdmsapp01.alpenland.local/``.
            Trailing slash is optional.
        api_url_base: Path prefix for the OSREST API, e.g. ``osrest/api/``.
        username: Basic-auth username.
        password: Basic-auth password.
        rendition_cache_url_base: Path prefix for the rendition cache, e.g.
            ``osrenditioncache/app/api/``. Optional — only required for download
            calls.
        ca_cert_file: Path to a PEM CA bundle for verifying the server cert.
            If ``None``, the system trust store is used (default).
        insecure: When True, **disables** TLS verification entirely. Only set
            this if you know what you are doing (e.g. self-signed cert in a
            disposable dev env). Logs a warning on every request.
        timeout: Per-request total timeout in seconds (default 30s).
        logger: Optional logger. Defaults to ``logging.getLogger(__name__)``.

    Raises:
        EnaioConfigError: when required arguments are missing/invalid.
    """

    def __init__(
        self,
        host: str,
        api_url_base: str,
        username: str,
        password: str,
        *,
        rendition_cache_url_base: str | None = None,
        ca_cert_file: str | None = None,
        insecure: bool = False,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        logger: logging.Logger | None = None,
    ) -> None:
        if not host:
            raise EnaioConfigError("'host' is required")
        if not api_url_base:
            raise EnaioConfigError("'api_url_base' is required")

        self.logger = logger or logging.getLogger(__name__)
        self.host = host.rstrip("/") + "/"
        self.api_url_base = api_url_base.lstrip("/")
        self.rendition_cache_url_base = (
            rendition_cache_url_base.lstrip("/") if rendition_cache_url_base else None
        )
        self._auth = aiohttp.BasicAuth(login=username, password=password)
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._ssl_context = self._build_ssl_context(ca_cert_file, insecure)
        self._insecure = insecure

        self._session: aiohttp.ClientSession | None = None
        self._owns_session = True

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    @classmethod
    def from_session(
        cls,
        session: aiohttp.ClientSession,
        *,
        host: str,
        api_url_base: str,
        username: str,
        password: str,
        rendition_cache_url_base: str | None = None,
        ca_cert_file: str | None = None,
        insecure: bool = False,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        logger: logging.Logger | None = None,
    ) -> "AsyncEnaioClient":
        """Wrap a borrowed :class:`aiohttp.ClientSession`.

        The caller is responsible for closing ``session``.
        """
        client = cls(
            host=host,
            api_url_base=api_url_base,
            username=username,
            password=password,
            rendition_cache_url_base=rendition_cache_url_base,
            ca_cert_file=ca_cert_file,
            insecure=insecure,
            timeout=timeout,
            logger=logger,
        )
        client._session = session
        client._owns_session = False
        return client

    @staticmethod
    def _build_ssl_context(
        ca_cert_file: str | None, insecure: bool
    ) -> ssl.SSLContext | bool | None:
        if insecure:
            # aiohttp accepts ``ssl=False`` for "do not verify".
            return False
        if ca_cert_file:
            return ssl.create_default_context(cafile=ca_cert_file)
        # ``None`` → defer to the session/connector default. This keeps
        # ``from_session`` users' connector settings (e.g. ``verify_ssl=False``
        # on a corporate self-signed cert) intact instead of forcing strict
        # verification on every request.
        return None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "AsyncEnaioClient":
        if self._session is None:
            self._session = aiohttp.ClientSession(
                auth=self._auth,
                timeout=self._timeout,
            )
            self._owns_session = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying session if owned."""
        if self._session is not None and self._owns_session:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------------

    def url(self, path: str) -> URL:
        """Build a URL under the OSREST API base."""
        return URL(self.host) / self.api_url_base / path.lstrip("/")

    def rendition_url(self, path: str) -> URL:
        """Build a URL under the rendition cache base."""
        if not self.rendition_cache_url_base:
            raise EnaioConfigError(
                "rendition_cache_url_base was not configured on this client"
            )
        return URL(self.host) / self.rendition_cache_url_base / path.lstrip("/")

    # ------------------------------------------------------------------
    # core requests
    # ------------------------------------------------------------------

    def _require_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise EnaioConfigError(
                "Client is not connected. Use 'async with AsyncEnaioClient(...)' "
                "or AsyncEnaioClient.from_session(...)."
            )
        return self._session

    async def get_json(
        self,
        url: URL | str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """GET ``url`` and parse the response as JSON.

        Raises:
            EnaioAuthError: on 401/403.
            EnaioNotFoundError: on 404.
            EnaioHTTPError: on any other non-2xx.
            EnaioResponseError: when the response is not valid JSON.
        """
        session = self._require_session()
        if self._insecure:
            self.logger.warning("TLS verification DISABLED for GET %s", url)

        async with session.get(url, params=params, ssl=self._ssl_context) as resp:
            await self._raise_for_status(resp)
            try:
                return await resp.json(content_type=None)
            except (aiohttp.ContentTypeError, ValueError) as exc:
                raise EnaioResponseError(
                    f"Failed to decode JSON from GET {url}: {exc}"
                ) from exc

    async def get_bytes(
        self,
        url: URL | str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> bytes:
        """GET ``url`` and return the raw response body."""
        session = self._require_session()
        if self._insecure:
            self.logger.warning("TLS verification DISABLED for GET %s", url)
        async with session.get(url, params=params, ssl=self._ssl_context) as resp:
            await self._raise_for_status(resp)
            return await resp.read()

    async def post_json(
        self,
        url: URL | str,
        *,
        json: Any = None,
        data: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """POST ``url`` and parse the response as JSON.

        Either ``json`` or ``data`` may be passed (mutually exclusive). When
        ``json`` is set, the ``Content-Type: application/json`` header is added
        per-request — *never* mutated on the shared session.
        """
        if json is not None and data is not None:
            raise ValueError("Pass either 'json' or 'data', not both.")

        session = self._require_session()

        merged_headers: dict[str, str] = {}
        if headers:
            merged_headers.update(headers)
        if json is not None:
            merged_headers.setdefault("Content-Type", "application/json")

        if self._insecure:
            self.logger.warning("TLS verification DISABLED for POST %s", url)

        async with session.post(
            url,
            json=json,
            data=data,
            headers=merged_headers or None,
            ssl=self._ssl_context,
        ) as resp:
            await self._raise_for_status(resp)
            try:
                return await resp.json(content_type=None)
            except (aiohttp.ContentTypeError, ValueError) as exc:
                raise EnaioResponseError(
                    f"Failed to decode JSON from POST {url}: {exc}"
                ) from exc

    async def _raise_for_status(self, resp: aiohttp.ClientResponse) -> None:
        if resp.status < 400:
            return
        body: Any
        try:
            body = await resp.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError):
            body = (await resp.text())[:512]

        url = str(resp.url)
        msg = f"Enaio HTTP {resp.status} for {url}: {body!r}"

        if resp.status in (401, 403):
            raise EnaioAuthError(resp.status, url, msg, body=body)
        if resp.status == 404:
            raise EnaioNotFoundError(resp.status, url, msg, body=body)
        raise EnaioHTTPError(resp.status, url, msg, body=body)

    # ------------------------------------------------------------------
    # high-level convenience
    # ------------------------------------------------------------------

    async def serviceinfo(self) -> dict[str, Any]:
        """GET /serviceinfo — also useful as a connectivity check."""
        return await self.get_json(self.url("serviceinfo"))

    async def check_osid_exists(self, osid: int | str) -> bool:
        """Return True iff the document/folder with ``osid`` exists.

        404 from the API maps to ``False``; all other HTTP errors propagate.
        """
        try:
            await self.get_json(self.url(f"documents/search/{osid}"))
        except EnaioNotFoundError:
            return False
        return True

    async def get_object(self, osid: int | str) -> dict[str, Any] | None:
        """Fetch a single object by OSID. Returns ``None`` on 404."""
        try:
            return await self.get_json(self.url(f"documents/search/{osid}/"))
        except EnaioNotFoundError:
            return None

    async def download_pdf(self, osid: int | str) -> bytes:
        """Download the PDF rendition of ``osid`` as bytes."""
        return await self.get_bytes(
            self.rendition_url(f"document/{osid}/rendition/pdf/")
        )

    async def download_zip(self, osid: int | str) -> bytes:
        """Download the original file of ``osid`` as a zip."""
        return await self.get_bytes(self.url(f"documentfiles/{osid}/zip"))
