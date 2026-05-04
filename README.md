# enaio-api-wrapper

Async Python client for the Enaio (OSREST) DMS API.

This is the v3 rewrite of the previous mixin-based, sync-only `enaio_api`
package. It is published as an installable Python distribution (no more git
submodules).

## Install

Editable from a local checkout:

```bash
pip install -e /path/to/enaio_api_wrapper
```

From git:

```bash
pip install "enaio-api-wrapper @ git+https://github.com/Limewood-Innovations/enaio-api-wrapper@v3.0.0"
```

## Usage

```python
import asyncio
from enaio_api_wrapper import AsyncEnaioClient, search_doc_cn

async def main() -> None:
    async with AsyncEnaioClient(
        host="https://alpdmsapp01.alpenland.local/",
        api_url_base="osrest/api/",
        username="enaioadmin",
        password="...",
        ca_cert_file="/etc/ssl/ca.crt",  # default verify=True
        timeout=30.0,
    ) as client:
        result = await search_doc_cn(
            client,
            object_type_id_doc=18,
            object_type_id_cab=17,
            doc_type=42,
            bkrs="1000",
            recnnr="ABC",
        )
        if result is not None:
            for osid in result.ids:
                print(osid, result.item_data[osid])

asyncio.run(main())
```

## What changed vs. v2

| v2 (mixin / requests)                              | v3 (this package)                                  |
| -------------------------------------------------- | -------------------------------------------------- |
| `class enaio(get_mixin, search_mixin, …)`          | `AsyncEnaioClient` — single class, no mixins       |
| Hard-coded credentials in `enaio_api/config.py`    | Config is the consumer's job                       |
| `verify=False` silent fallback                     | `verify=True` default; `insecure=True` is explicit |
| `requests.Session` + `__del__`                     | `aiohttp.ClientSession` + `async with`             |
| Returns `None` for any error                       | Typed exceptions (`EnaioHTTPError`, …)             |
| `request_json['query']['result_config'] = …`       | Defensive `deepcopy`, no caller-dict mutation      |
| Mixin attributes shared by convention              | Plain attributes, full type hints                  |
| No `pyproject.toml`, install via submodule         | PEP 621 build, `pip install`                       |
| Pagination loop with no max-pages guard            | `max_pages=` cap (default 100)                     |
| `"%s" % x` everywhere                              | `str(x)` / f-strings                               |

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src tests
mypy src
```
