from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from flatview.models import Listing


def _extract_jsonld(html: str) -> dict | None:
    """Extract the schema.org JSON-LD graph from nehnutelnosti.sk RSC payload."""
    soup = BeautifulSoup(html, "lxml")

    # Collect all self.__next_f.push() payload strings
    push_contents: list[str] = []
    for script in soup.select("script"):
        s = script.string
        if not s or "self.__next_f.push" not in s:
            continue
        m = re.match(r'self\.__next_f\.push\(\[1,"(.*)"\]\)\s*$', s, re.DOTALL)
        if m:
            push_contents.append(m.group(1))
        else:
            m2 = re.match(r"self\.__next_f\.push\(\[1,(.*)\]\)\s*$", s, re.DOTALL)
            if m2:
                push_contents.append(m2.group(1))

    # Find the chunk containing @context/schema.org and concatenate subsequent chunks
    jsonld_text = ""
    collecting = False
    for chunk in push_contents:
        if "@context" in chunk and "schema.org" in chunk:
            idx = chunk.find("{")
            if idx >= 0:
                jsonld_text = chunk[idx:]
                collecting = True
                continue
        if collecting:
            jsonld_text += chunk

    if not jsonld_text:
        return None

    # Unescape JS string layer: the regex capture gives us content where
    # \" is literal backslash+quote, \n is literal backslash+n, etc.
    text = jsonld_text.replace("\\\\", "\x00BS\x00")  # preserve real backslashes
    text = text.replace('\\"', '"')
    text = text.replace("\\n", "\n")
    text = text.replace("\\r", "\r")
    text = text.replace("\\t", "\t")
    text = text.replace("\\/", "/")
    text = text.replace("\x00BS\x00", "\\")

    try:
        decoder = json.JSONDecoder(strict=False)
        data, _ = decoder.raw_decode(text)
        return data
    except (json.JSONDecodeError, ValueError):
        return None


def parse_nehnutelnosti_listings(html: str) -> list[Listing]:
    """Parse listings from nehnutelnosti.sk search results page."""
    data = _extract_jsonld(html)
    if not data:
        return []

    graph = data.get("@graph", [])
    listings: list[Listing] = []

    for item in graph:
        if item.get("@type") != "SearchResultsPage":
            continue
        main_entity = item.get("mainEntity", {})
        if main_entity.get("@type") != "ItemList":
            continue

        for elem in main_entity.get("itemListElement", []):
            it = elem.get("item", {})
            listing = _parse_item(it)
            if listing:
                listings.append(listing)
        break

    return listings


def parse_nehnutelnosti_total_count(html: str) -> int | None:
    """Extract total results count from nehnutelnosti.sk page."""
    data = _extract_jsonld(html)
    if not data:
        # Fallback: look for "X inzerátov" in metadata
        match = re.search(r"\((\d[\d\s]*)\s*inzerátov\)", html)
        if match:
            return int(match.group(1).replace(" ", "").replace("\xa0", ""))
        return None

    graph = data.get("@graph", [])
    for item in graph:
        if item.get("@type") == "SearchResultsPage":
            main_entity = item.get("mainEntity", {})
            count = main_entity.get("numberOfItems")
            if count is not None:
                return int(count)
    return None


def _parse_item(item: dict) -> Listing | None:
    """Parse a single JSON-LD listing item into a Listing."""
    name = item.get("name")
    if not name:
        return None

    # Price from priceSpecification
    price = None
    currency = "EUR"
    ps = item.get("priceSpecification", {})
    if isinstance(ps, dict):
        raw_price = ps.get("price")
        if raw_price is not None:
            try:
                price = float(raw_price)
            except (ValueError, TypeError):
                pass
        currency = ps.get("priceCurrency", "EUR")

    # Treat price=0 as no price
    if price == 0:
        price = None

    # Area from floorSize
    area = None
    fs = item.get("floorSize", {})
    if isinstance(fs, dict):
        raw_area = fs.get("value")
        if raw_area is not None:
            try:
                area = float(raw_area)
            except (ValueError, TypeError):
                pass
    # floorSize=1 is a placeholder on nehnutelnosti.sk
    if area is not None and area <= 1:
        area = None

    # URL
    url = item.get("url", "")

    # Extract listing ID from URL (e.g. /detail/Juy_iQKPxuI/...)
    listing_id = None
    id_match = re.search(r"/detail/([^/]+)/", url)
    if id_match:
        listing_id = id_match.group(1)

    return Listing(
        title=name,
        price=price,
        currency=currency,
        city="",  # Not available in JSON-LD; inferred from URL/location filter
        postcode="",
        date="",
        url=url,
        source="nehnutelnosti",
        area=area,
        id=listing_id,
    )
