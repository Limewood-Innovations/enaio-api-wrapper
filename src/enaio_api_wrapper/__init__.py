"""enaio_api_wrapper — async Python client for the Enaio (OSREST) DMS API."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from .client import AsyncEnaioClient
from .exceptions import (
    EnaioAuthError,
    EnaioConfigError,
    EnaioError,
    EnaioHTTPError,
    EnaioNotFoundError,
    EnaioResponseError,
)
from .models import SearchResult
from .search import (
    basic_doc_search,
    search_doc_bp,
    search_doc_cn,
    search_doc_gs,
    search_doc_mo,
    search_doc_we,
)

try:
    __version__ = _pkg_version("enaio-api-wrapper")
except PackageNotFoundError:  # pragma: no cover - editable install w/o metadata
    __version__ = "0.0.0+local"

__all__ = [
    "AsyncEnaioClient",
    "EnaioAuthError",
    "EnaioConfigError",
    "EnaioError",
    "EnaioHTTPError",
    "EnaioNotFoundError",
    "EnaioResponseError",
    "SearchResult",
    "basic_doc_search",
    "search_doc_bp",
    "search_doc_cn",
    "search_doc_gs",
    "search_doc_mo",
    "search_doc_we",
    "__version__",
]
