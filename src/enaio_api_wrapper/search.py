"""High-level document-search helpers.

These functions call ``POST {host}{api_url_base}documents/search/`` with the
appropriate query payload and return a :class:`SearchResult` (or ``None``
when there were zero hits).

Compared to the v2 mixin implementation:

* The caller's ``query`` dict is **not mutated** (defensive deepcopy).
* Pagination is bounded by ``max_pages`` to prevent infinite loops on
  pathological API responses.
* All numeric IDs are coerced via ``str()`` exactly once at the call site,
  not via ``"%s" % x`` sprinkled through nested dicts.
* Errors raise typed exceptions rather than returning ``None`` for everything.
"""

from __future__ import annotations

import copy
from typing import Any, TYPE_CHECKING

from .models import SearchResult

if TYPE_CHECKING:
    from .client import AsyncEnaioClient


_DEFAULT_PAGESIZE = 500
_DEFAULT_MAX_PAGES = 100


async def basic_doc_search(
    client: "AsyncEnaioClient",
    query: dict[str, Any],
    *,
    additional_queries: list[dict[str, Any]] | None = None,
    sort_by: str | None = None,
    sort_order: str = "DESC",
    fieldsschema: list[dict[str, Any]] | None = None,
    fieldsschema_mode: str = "ALL",
    maxhits: int = 0,
    pagesize: int = _DEFAULT_PAGESIZE,
    offset: int = 0,
    max_pages: int = _DEFAULT_MAX_PAGES,
) -> SearchResult | None:
    """Run a paginated document search against the Enaio API.

    Pagination semantics (Code Review F-014):

    * ``maxhits`` is a **client-side** ceiling on the total number of hits
      returned across all pages. ``0`` means "no client-side cap" — but the
      server still applies its own limits.
    * ``pagesize`` is the per-page request size (default 500). The loop
      terminates as soon as a page returns **fewer than ``pagesize`` items**
      (the standard "last page reached" signal). It also terminates if the
      server ever returns a page that doesn't advance the offset (loop
      protection) or if ``max_pages`` is exhausted (safety cap).
    * If both ``pagesize`` and ``maxhits`` are positive, the per-request
      pagesize is capped at ``maxhits - len(ids)`` so we never over-fetch.

    Args:
        client: An :class:`AsyncEnaioClient`. Must be entered (``async with``).
        query: The Enaio query dict, e.g.
            ``{"objectTypeId": "18", "fields": {"DocID": {"value": "..."}}}``.
            **Not mutated.**
        additional_queries: Optional list of additional query dicts (joined
            cabinet/folder filtering).
        sort_by: Internal field name to sort by. Mutually informative with
            ``fieldsschema``: if ``fieldsschema`` is given it wins, else if
            ``sort_by`` is given a single-field schema is built from it.
        sort_order: ``"ASC"`` or ``"DESC"``.
        fieldsschema: Explicit fields schema list.
        fieldsschema_mode: ``"ALL"``/``"DEF"``/``"MIN"`` (Enaio-side filter).
        maxhits: Client-side cap on total hits. ``0`` = no cap.
        pagesize: Page size (default 500).
        offset: Initial offset.
        max_pages: Safety cap on pagination iterations (default 100).

    Returns:
        :class:`SearchResult` on success, ``None`` when the API returned
        zero documents.

    Raises:
        EnaioHTTPError: on any non-2xx HTTP response.
        EnaioResponseError: on malformed JSON.
        ValueError: when ``pagesize <= 0``.
    """
    if pagesize <= 0:
        raise ValueError(f"pagesize must be > 0, got {pagesize}")
    api_url = client.url("documents/search/")

    # Build result_config locally — never mutate caller's query.
    result_config: dict[str, Any] = {
        "baseParameters": 0,
        "systemFields": 0,
        "fileProperties": 0,
        "export_depth": 1,
        "maxhits": maxhits,
        "pagesize": pagesize,
        "offset": offset,
    }

    if fieldsschema is not None:
        result_config["fieldsschema_mode"] = fieldsschema_mode
        result_config["fieldsschema"] = fieldsschema
    elif sort_by is not None:
        result_config["fieldsschema_mode"] = "ALL"
        result_config["fieldsschema"] = [
            {"internalName": str(sort_by), "sort_pos": 1, "sort_order": str(sort_order)}
        ]
    else:
        result_config["fieldsschema_mode"] = fieldsschema_mode

    request_body: dict[str, Any] = {"query": copy.deepcopy(query)}
    request_body["query"]["result_config"] = result_config
    if additional_queries:
        if not isinstance(additional_queries, list):
            raise TypeError("additional_queries must be a list of dicts")
        request_body["additionalQueries"] = copy.deepcopy(additional_queries)

    ids: list[str] = []
    item_data: dict[str, Any] = {}
    seen_offsets: set[int] = set()

    for page in range(max_pages):
        # Guard 1: detect server returning the same offset twice (would loop forever).
        if offset in seen_offsets:
            client.logger.warning(
                "basic_doc_search: offset %s already seen (page %s) — stopping to "
                "avoid infinite loop.",
                offset,
                page,
            )
            break
        seen_offsets.add(offset)

        # Guard 2: enforce client-side maxhits — never request more than we need.
        if maxhits > 0:
            remaining = maxhits - len(ids)
            if remaining <= 0:
                break
            request_pagesize = min(pagesize, remaining)
        else:
            request_pagesize = pagesize

        request_body["query"]["result_config"]["offset"] = offset
        request_body["query"]["result_config"]["pagesize"] = request_pagesize

        client.logger.debug(
            "basic_doc_search request page=%s offset=%s pagesize=%s",
            page,
            offset,
            request_pagesize,
        )
        response = await client.post_json(api_url, json=request_body)

        if not response:
            client.logger.debug("basic_doc_search: empty page at offset %s", offset)
            break

        if not isinstance(response, list):
            client.logger.warning(
                "basic_doc_search: unexpected response shape (%s); treating as no-results",
                type(response).__name__,
            )
            break

        page_count = len(response)
        client.logger.debug(
            "basic_doc_search results from %s to %s", offset, offset + page_count
        )

        for item in response:
            try:
                osid = item["osid"]
            except (KeyError, TypeError):
                client.logger.warning("basic_doc_search: item without 'osid' skipped: %r", item)
                continue
            ids.append(osid)
            item_data[osid] = item
            # Stop mid-page if we've reached the client cap.
            if maxhits > 0 and len(ids) >= maxhits:
                break

        if maxhits > 0 and len(ids) >= maxhits:
            break

        offset += page_count
        # Standard "last page" signal — server returned a short page.
        if page_count < request_pagesize:
            break
    else:
        client.logger.warning(
            "basic_doc_search: hit max_pages=%s — possible runaway pagination", max_pages
        )

    if not ids:
        return None
    return SearchResult(ids=ids, item_data=item_data)


# ---------------------------------------------------------------------------
# Domain-specific helpers (Alpenland-Schemata)
# ---------------------------------------------------------------------------


async def search_doc_we(
    client: "AsyncEnaioClient",
    *,
    object_type_id_doc: int | str,
    object_type_id_cab: int | str,
    doc_type: int | str,
    bkrs: int | str,
    swenr: int | str,
    sort_by: str | None = None,
    sort_order: str = "DESC",
    maxhits: int = 1,
    extra_filters: dict[str, str] | None = None,
) -> SearchResult | None:
    """Search documents of ``doc_type`` filtered by WE cabinet
    (``BKRS`` + ``WE``).

    ``extra_filters`` is an optional ``dict[str, str]`` that the caller
    can use to apply additional ``fields`` constraints on the document
    side of the query (e.g. ``{"Verifiziert": "1"}`` for the Alpenland
    portal-side rule "only QA'd documents"). The wrapper itself stays
    business-rule-free.
    """
    client.logger.debug("search_doc_we BKRS=%s WE=%s", bkrs, swenr)
    query = {
        "objectTypeId": str(object_type_id_doc),
        "fields": {
            "Unterlagenart": {"value": str(doc_type)},
            **{k: {"value": v} for k, v in (extra_filters or {}).items()},
        },
    }
    additional = [
        {
            "objectTypeId": str(object_type_id_cab),
            "fields": {
                "BKRS": {"value": str(bkrs)},
                "WE": {"value": str(swenr)},
            },
        }
    ]
    return await basic_doc_search(
        client,
        query,
        additional_queries=additional,
        sort_by=sort_by,
        sort_order=sort_order,
        fieldsschema_mode="ALL",
        maxhits=maxhits,
    )


async def search_doc_gs(
    client: "AsyncEnaioClient",
    *,
    object_type_id_doc: int | str,
    object_type_id_cab: int | str,
    doc_type: int | str,
    bkrs: int | str,
    swenr: int | str,
    sort_by: str | None = None,
    sort_order: str = "DESC",
    maxhits: int = 0,
    extra_filters: dict[str, str] | None = None,
) -> SearchResult | None:
    """Search documents of ``doc_type`` filtered by GS cabinet
    (``BKRS`` + ``Projekt WE``)."""
    client.logger.debug("search_doc_gs BKRS=%s ProjektWE=%s", bkrs, swenr)
    query = {
        "objectTypeId": str(object_type_id_doc),
        "fields": {
            "Unterlagenart": {"value": str(doc_type)},
            **{k: {"value": v} for k, v in (extra_filters or {}).items()},
        },
    }
    additional = [
        {
            "objectTypeId": str(object_type_id_cab),
            "fields": {
                "BKRS": {"value": str(bkrs)},
                "Projekt WE": {"value": str(swenr)},
            },
        }
    ]
    return await basic_doc_search(
        client,
        query,
        additional_queries=additional,
        sort_by=sort_by,
        sort_order=sort_order,
        fieldsschema_mode="ALL",
        maxhits=maxhits,
    )


async def search_doc_mo(
    client: "AsyncEnaioClient",
    *,
    object_type_id_doc: int | str,
    object_type_id_cab: int | str,
    doc_type: int | str,
    bkrs: int | str,
    swenr: int | str,
    smenr: int | str,
    sort_by: str | None = None,
    sort_order: str = "DESC",
    maxhits: int = 1,
    extra_filters: dict[str, str] | None = None,
) -> SearchResult | None:
    """Search documents of ``doc_type`` filtered by MO cabinet
    (``BKRS`` + ``WE`` + ``MONummer``).

    See :func:`search_doc_we` for ``extra_filters`` semantics.
    """
    client.logger.debug("search_doc_mo BKRS=%s WE=%s MO=%s", bkrs, swenr, smenr)
    query = {
        "objectTypeId": str(object_type_id_doc),
        "fields": {
            "Unterlagenart": {"value": str(doc_type)},
            **{k: {"value": v} for k, v in (extra_filters or {}).items()},
        },
    }
    additional = [
        {
            "objectTypeId": str(object_type_id_cab),
            "fields": {
                "BKRS": {"value": str(bkrs)},
                "WE": {"value": str(swenr)},
                "MONummer": {"value": str(smenr)},
            },
        }
    ]
    return await basic_doc_search(
        client,
        query,
        additional_queries=additional,
        sort_by=sort_by,
        sort_order=sort_order,
        fieldsschema_mode="ALL",
        maxhits=maxhits,
    )


async def search_doc_bp(
    client: "AsyncEnaioClient",
    *,
    object_type_id_doc: int | str,
    object_type_id_cab: int | str,
    doc_type: int | str,
    bpnr: int | str,
    sort_by: str | None = None,
    sort_order: str = "DESC",
    maxhits: int = 0,
    extra_filters: dict[str, str] | None = None,
) -> SearchResult | None:
    """Search documents of ``doc_type`` filtered by business-partner
    (``GP Nummer``)."""
    client.logger.debug("search_doc_bp GP=%s", bpnr)
    query = {
        "objectTypeId": str(object_type_id_doc),
        "fields": {
            "Unterlagenart": {"value": str(doc_type)},
            **{k: {"value": v} for k, v in (extra_filters or {}).items()},
        },
    }
    additional = [
        {
            "objectTypeId": str(object_type_id_cab),
            "fields": {"GP Nummer": {"value": str(bpnr)}},
        }
    ]
    return await basic_doc_search(
        client,
        query,
        additional_queries=additional,
        sort_by=sort_by,
        sort_order=sort_order,
        fieldsschema_mode="ALL",
        maxhits=maxhits,
    )


async def search_doc_cn(
    client: "AsyncEnaioClient",
    *,
    object_type_id_doc: int | str,
    object_type_id_cab: int | str,
    doc_type: int | str,
    bkrs: int | str,
    recnnr: int | str,
    sort_by: str | None = None,
    sort_order: str = "DESC",
    maxhits: int = 0,
    extra_filters: dict[str, str] | None = None,
) -> SearchResult | None:
    """Search documents of ``doc_type`` filtered by contract cabinet
    (``Vertrag`` + ``Buchungskreis``)."""
    client.logger.debug("search_doc_cn Vertrag=%s BKRS=%s", recnnr, bkrs)
    query = {
        "objectTypeId": str(object_type_id_doc),
        "fields": {
            "Unterlagenart": {"value": str(doc_type)},
            **{k: {"value": v} for k, v in (extra_filters or {}).items()},
        },
    }
    additional = [
        {
            "objectTypeId": str(object_type_id_cab),
            "fields": {
                "Vertrag": {"value": str(recnnr)},
                "Buchungskreis": {"value": str(bkrs)},
            },
        }
    ]
    return await basic_doc_search(
        client,
        query,
        additional_queries=additional,
        sort_by=sort_by,
        sort_order=sort_order,
        fieldsschema_mode="ALL",
        maxhits=maxhits,
    )
