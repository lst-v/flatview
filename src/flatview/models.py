from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Segment = Literal["new", "resale", "unknown"]
OutlierSide = Literal["bargain", "overpriced"]


@dataclass
class Listing:
    title: str
    price: float | None
    currency: str
    city: str
    postcode: str
    date: str
    url: str
    views: int | None = None
    # bazos/topreality use numeric ids; nehnutelnosti uses a URL slug string.
    id: int | str | None = None
    source: str = "bazos"
    area: float | None = None
    description: str | None = None
    segment: Segment = "unknown"
    is_outlier: bool = False
    outlier_side: OutlierSide | None = None
    first_seen: str | None = None
    previous_price: float | None = None


@dataclass
class SearchResult:
    listings: list[Listing] = field(default_factory=list)
    total_count: int | None = None
    query: str = ""
    category: str = ""
    location: str = ""
    site: str = "bazos.sk"
    # Set when a page fetch failed; lets callers tell "empty" from "unreachable".
    error: str | None = None
