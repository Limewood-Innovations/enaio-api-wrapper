"""Smoke tests for search helpers."""

from __future__ import annotations

import copy
import json

from aresponses import ResponsesMockServer

from enaio_api_wrapper import (
    AsyncEnaioClient,
    SearchResult,
    basic_doc_search,
    search_doc_cn,
    search_doc_we,
)


def _doc(osid: str, **extra: object) -> dict[str, object]:
    return {"osid": osid, **extra}


async def test_basic_doc_search_returns_none_when_empty(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    aresponses.add(
        "test.invalid",
        "/osrest/api/documents/search/",
        "POST",
        aresponses.Response(status=200, text="[]"),
    )
    assert await basic_doc_search(client, {"objectTypeId": "18"}) is None


async def test_basic_doc_search_collects_ids(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    aresponses.add(
        "test.invalid",
        "/osrest/api/documents/search/",
        "POST",
        aresponses.Response(
            status=200,
            text=json.dumps([_doc("1"), _doc("2"), _doc("3")]),
        ),
    )
    result = await basic_doc_search(client, {"objectTypeId": "18"})
    assert isinstance(result, SearchResult)
    assert result.ids == ["1", "2", "3"]
    assert set(result.item_data) == {"1", "2", "3"}


async def test_basic_doc_search_pagination_two_pages(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    full_page = [_doc(str(i)) for i in range(500)]
    last_page = [_doc(str(i)) for i in range(500, 510)]
    aresponses.add(
        "test.invalid",
        "/osrest/api/documents/search/",
        "POST",
        aresponses.Response(status=200, text=json.dumps(full_page)),
    )
    aresponses.add(
        "test.invalid",
        "/osrest/api/documents/search/",
        "POST",
        aresponses.Response(status=200, text=json.dumps(last_page)),
    )
    result = await basic_doc_search(client, {"objectTypeId": "18"})
    assert result is not None
    assert len(result.ids) == 510


async def test_basic_doc_search_does_not_mutate_caller_query(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    aresponses.add(
        "test.invalid",
        "/osrest/api/documents/search/",
        "POST",
        aresponses.Response(status=200, text="[]"),
    )
    query = {"objectTypeId": "18", "fields": {"DocID": {"value": "abc"}}}
    snapshot = copy.deepcopy(query)
    await basic_doc_search(client, query)
    assert query == snapshot


async def test_search_doc_we_builds_expected_payload(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    captured: dict[str, object] = {}

    async def handler(request):
        captured["body"] = await request.json()
        return aresponses.Response(status=200, text="[]")

    aresponses.add("test.invalid", "/osrest/api/documents/search/", "POST", handler)

    await search_doc_we(
        client,
        object_type_id_doc=18,
        object_type_id_cab=17,
        doc_type=42,
        bkrs=1000,
        swenr=999,
    )

    body = captured["body"]
    assert body["query"]["objectTypeId"] == "18"
    assert body["query"]["fields"]["Unterlagenart"] == {"value": "42"}
    additional = body["additionalQueries"]
    assert additional[0]["objectTypeId"] == "17"
    assert additional[0]["fields"]["BKRS"] == {"value": "1000"}
    assert additional[0]["fields"]["WE"] == {"value": "999"}


async def test_basic_doc_search_respects_client_maxhits(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    """maxhits=3 must cap result count even if server returns a full page."""
    aresponses.add(
        "test.invalid",
        "/osrest/api/documents/search/",
        "POST",
        aresponses.Response(
            status=200, text=json.dumps([_doc(str(i)) for i in range(10)])
        ),
    )
    result = await basic_doc_search(client, {"objectTypeId": "18"}, maxhits=3)
    assert result is not None
    assert len(result.ids) == 3
    assert result.ids == ["0", "1", "2"]


async def test_basic_doc_search_pagesize_must_be_positive(
    client: AsyncEnaioClient,
) -> None:
    import pytest as _pytest
    with _pytest.raises(ValueError):
        await basic_doc_search(client, {"objectTypeId": "18"}, pagesize=0)


async def test_basic_doc_search_terminates_on_short_page(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    """A page shorter than the requested pagesize must end the loop without
    issuing another request."""
    aresponses.add(
        "test.invalid",
        "/osrest/api/documents/search/",
        "POST",
        aresponses.Response(status=200, text=json.dumps([_doc("1"), _doc("2")])),
    )
    # No second stub registered — if the loop tries another page, aresponses
    # raises NoRouteFoundError.
    result = await basic_doc_search(client, {"objectTypeId": "18"}, pagesize=500)
    assert result is not None
    assert result.ids == ["1", "2"]


async def test_search_doc_cn_builds_expected_payload(
    aresponses: ResponsesMockServer, client: AsyncEnaioClient
) -> None:
    captured: dict[str, object] = {}

    async def handler(request):
        captured["body"] = await request.json()
        return aresponses.Response(status=200, text="[]")

    aresponses.add("test.invalid", "/osrest/api/documents/search/", "POST", handler)

    await search_doc_cn(
        client,
        object_type_id_doc=18,
        object_type_id_cab=17,
        doc_type=42,
        bkrs=1000,
        recnnr="ABC",
    )

    body = captured["body"]
    assert body["query"]["fields"]["Verifiziert"] == {"value": "1"}
    additional = body["additionalQueries"]
    assert additional[0]["fields"]["Vertrag"] == {"value": "ABC"}
    assert additional[0]["fields"]["Buchungskreis"] == {"value": "1000"}
