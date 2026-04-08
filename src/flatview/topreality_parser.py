from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from flatview.models import Listing

_BASE_URL = "https://www.topreality.sk"


def parse_topreality_total_count(html: str) -> int | None:
    match = re.search(r"([\d\s]+)\s*inzerátov", html)
    if not match:
        return None
    digits = match.group(1).replace(" ", "").replace("\xa0", "")
    return int(digits) if digits else None


def parse_topreality_listings(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select(".row.estate")
    listings: list[Listing] = []
    for card in cards:
        listing = _parse_card(card)
        if listing:
            listings.append(listing)
    return listings


def _parse_card(card: Tag) -> Listing | None:
    title_el = card.select_one(".card-title a")
    if not title_el:
        return None

    title = title_el.get_text(strip=True)
    href = title_el.get("href", "")
    if href and not href.startswith("http"):
        href = _BASE_URL + href
    url = href

    listing_id = None
    try:
        listing_id = int(card["data-idinz"])
    except (KeyError, ValueError, TypeError):
        pass

    price = _parse_price(card)
    city = ""
    city_el = card.select_one(".location-city")
    if city_el:
        city = city_el.get_text(strip=True)

    area = _parse_area(card)

    return Listing(
        title=title,
        price=price,
        currency="EUR",
        city=city,
        postcode="",
        date="",
        url=url,
        id=listing_id,
        source="topreality",
        area=area,
    )


def _parse_price(card: Tag) -> float | None:
    price_el = card.select_one(".price")
    if not price_el:
        return None
    text = price_el.get_text(strip=True)
    if re.search(r"(?i)dohodou|vyžiadanie", text):
        return None
    match = re.search(r"[\d\s\xa0]+", text)
    if not match:
        return None
    digits = match.group().replace(" ", "").replace("\xa0", "")
    if not digits:
        return None
    try:
        return float(int(digits))
    except ValueError:
        return None


def _parse_area(card: Tag) -> float | None:
    for selector in (".area-floor", ".area-building"):
        el = card.select_one(selector)
        if el:
            text = el.get_text(strip=True)
            match = re.search(r"([\d,\.]+)", text)
            if match:
                val = float(match.group(1).replace(",", "."))
                if val > 1:
                    return val
    return None
