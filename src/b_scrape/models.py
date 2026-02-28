from __future__ import annotations

from dataclasses import dataclass, field


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
    id: int | None = None


@dataclass
class SearchResult:
    listings: list[Listing] = field(default_factory=list)
    total_count: int | None = None
    query: str = ""
    category: str = ""
    location: str = ""
    site: str = "bazos.sk"
