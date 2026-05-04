"""Typed return models for the Enaio API wrapper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SearchResult:
    """Result of a document search.

    Attributes:
        ids: List of OSIDs returned (insertion order).
        item_data: Mapping ``osid -> raw response dict``.
    """

    ids: list[str] = field(default_factory=list)
    item_data: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.ids)

    def __len__(self) -> int:
        return len(self.ids)
