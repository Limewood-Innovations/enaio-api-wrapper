"""Exception hierarchy for enaio_api_wrapper.

All errors raised by this package inherit from :class:`EnaioError`. Consumers
that want to catch *any* enaio failure can do::

    try:
        await client.get_object(osid)
    except EnaioError:
        ...
"""

from __future__ import annotations

from typing import Any


class EnaioError(Exception):
    """Base class for all errors raised by this package."""


class EnaioConfigError(EnaioError):
    """Raised when the client is misconfigured (e.g. missing host)."""


class EnaioHTTPError(EnaioError):
    """A non-2xx response was returned by the Enaio API."""

    def __init__(
        self,
        status: int,
        url: str,
        message: str | None = None,
        body: Any = None,
    ) -> None:
        self.status = status
        self.url = url
        self.body = body
        super().__init__(message or f"Enaio HTTP {status} for {url}")


class EnaioAuthError(EnaioHTTPError):
    """401/403 from the Enaio API. Subclass of :class:`EnaioHTTPError`."""


class EnaioNotFoundError(EnaioHTTPError):
    """404 from the Enaio API. Subclass of :class:`EnaioHTTPError`."""


class EnaioResponseError(EnaioError):
    """The response body did not match the expected schema."""
