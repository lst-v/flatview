from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from b_scrape.models import Listing


AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*m[²2]", re.IGNORECASE)


def parse_detail_area(html: str) -> float | None:
    """Extract floor area (m²) from a bazos detail page."""
    soup = BeautifulSoup(html, "lxml")

    # Detect deleted listings
    mc = soup.select_one("div.maincontent")
    if mc and "vymazaný" in mc.get_text()[:100]:
        return None

    # div.popisdetail is the actual listing description on detail pages
    desc = soup.select_one("div.popisdetail")
    if not desc:
        return None
    text = desc.get_text()
    match = AREA_RE.search(text)
    if match:
        val = float(match.group(1).replace(",", "."))
        return val if val > 1 else None
    return None


def parse_listings(html: str, site: str = "bazos.sk") -> list[Listing]:
    """Parse listing cards from a bazos search results page."""
    soup = BeautifulSoup(html, "lxml")
    listings: list[Listing] = []

    # Each listing is in a div.inzeraty.inzeratyflex
    for card in soup.select("div.inzeraty.inzeratyflex"):
        listing = _parse_card(card, site)
        if listing:
            listings.append(listing)

    return listings


def parse_total_count(html: str) -> int | None:
    """Extract total results count from the page.

    Bazos shows "Zobrazených 1-20 inzerátov z 84".
    """
    soup = BeautifulSoup(html, "lxml")
    header = soup.select_one("div.listainzerat div.inzeratynadpis")
    if header:
        text = header.get_text()
        match = re.search(r"z\s+(\d[\d\s]*)", text)
        if match:
            return int(match.group(1).replace(" ", "").replace("\xa0", ""))
    return None


def _parse_card(card: Tag, site: str) -> Listing | None:
    """Parse a single listing card element."""
    # Title and URL from h2.nadpis > a
    nadpis = card.select_one("h2.nadpis a")
    if not nadpis:
        return None

    title = nadpis.get_text(strip=True)
    href = nadpis.get("href", "")
    if href.startswith("/"):
        # Category subdomain — extract from parent URL context
        url = f"https://{_guess_subdomain(card, site)}.{site}{href}"
    else:
        url = href

    # Extract listing ID from URL
    listing_id = None
    id_match = re.search(r"/inzerat/(\d+)/", url)
    if id_match:
        listing_id = int(id_match.group(1))

    # Price — div.inzeratycena
    price = None
    currency = "EUR" if site.endswith(".sk") else "CZK"
    price_el = card.select_one("div.inzeratycena")
    if price_el:
        price_text = price_el.get_text(strip=True)
        price, currency = _parse_price(price_text, currency)

    # Location — div.inzeratylok (city<br>postcode)
    city = ""
    postcode = ""
    loc_el = card.select_one("div.inzeratylok")
    if loc_el:
        parts = list(loc_el.stripped_strings)
        if parts:
            city = parts[0]
        if len(parts) >= 2:
            postcode = parts[1]

    # Date — [28.2. 2026] in the nadpis area
    date = ""
    nadpis_div = card.select_one("div.inzeratynadpis")
    if nadpis_div:
        date_match = re.search(r"\[(.+?)\]", nadpis_div.get_text())
        if date_match:
            date = date_match.group(1).strip()

    # Views — div.inzeratyview
    views = None
    views_el = card.select_one("div.inzeratyview")
    if views_el:
        views_text = views_el.get_text(strip=True)
        views_match = re.search(r"(\d[\d\s]*)", views_text)
        if views_match:
            views = int(views_match.group(1).replace(" ", ""))

    return Listing(
        title=title,
        price=price,
        currency=currency,
        city=city,
        postcode=postcode,
        date=date,
        url=url,
        views=views,
        id=listing_id,
    )


def _guess_subdomain(card: Tag, site: str) -> str:
    """Try to find the category subdomain from context."""
    # Look for an absolute link in the card to extract subdomain
    for a in card.select("a[href^='https://']"):
        href = a.get("href", "")
        match = re.match(rf"https://(\w+)\.{re.escape(site)}", href)
        if match:
            return match.group(1)
    return "www"


def _parse_price(text: str, default_currency: str) -> tuple[float | None, str]:
    """Parse price text like '89 900 €' or 'Dohodou'."""
    currency = default_currency
    if "€" in text:
        currency = "EUR"
    elif "Kč" in text.lower() or "czk" in text.lower():
        currency = "CZK"

    # Remove currency symbols and whitespace, try to parse number
    cleaned = text.replace("€", "").replace("Kč", "").replace("\xa0", "").strip()
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = cleaned.replace(",", ".")
    if not cleaned or not re.search(r"\d", cleaned):
        return None, currency

    # Extract the numeric part
    num_match = re.search(r"[\d.]+", cleaned)
    if not num_match:
        return None, currency

    try:
        return float(num_match.group(0)), currency
    except ValueError:
        return None, currency
