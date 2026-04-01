from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlencode


TRANSACTION_MAP = {
    "predam": "predaj",
    "prenajmu": "prenajom",
}

PROPERTY_MAP = {
    "byt": "byty",
    "dom": "domy",
    "pozemok": "pozemky",
    "priestor": "priestory",
}

ROOM_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"1[- ]?izb", re.IGNORECASE), "1-izbove-byty"),
    (re.compile(r"2[- ]?izb", re.IGNORECASE), "2-izbove-byty"),
    (re.compile(r"3[- ]?izb", re.IGNORECASE), "3-izbove-byty"),
    (re.compile(r"4[- ]?izb", re.IGNORECASE), "4-izbove-byty"),
    (re.compile(r"5[- ]?izb", re.IGNORECASE), "5-a-viac-izbove-byty"),
    (re.compile(r"gars[oó]n", re.IGNORECASE), "garsonky"),
]


def _slugify(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    return ascii_text.lower().replace(" ", "-")


def build_nehnutelnosti_url(
    query: str = "",
    subcategory: str = "",
    location: str = "",
    price_from: int | None = None,
    price_to: int | None = None,
    page: int = 1,
) -> str:
    transaction = ""
    property_type = ""

    if subcategory:
        parts = subcategory.strip("/").split("/")
        if parts:
            transaction = TRANSACTION_MAP.get(parts[0], parts[0])
        if len(parts) >= 2:
            property_type = PROPERTY_MAP.get(parts[1], parts[1])

    # Refine property type from query (e.g. "2 izbový" -> "2-izbove-byty")
    if query:
        for pattern, slug in ROOM_PATTERNS:
            if pattern.search(query):
                property_type = slug
                break

    # Build path segments — order: property / location / transaction
    segments = ["vysledky"]
    if property_type:
        segments.append(property_type)
    if location:
        segments.append(_slugify(location))
    if transaction:
        segments.append(transaction)

    path = "/" + "/".join(segments)

    params: dict[str, str | int] = {}
    if page > 1:
        params["page"] = page
    if price_from is not None:
        params["cena-od"] = price_from
    if price_to is not None:
        params["cena-do"] = price_to

    url = f"https://www.nehnutelnosti.sk{path}"
    if params:
        url += "?" + urlencode(params)
    return url
