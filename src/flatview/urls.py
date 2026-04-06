from __future__ import annotations

from urllib.parse import urlencode


def build_search_url(
    category: str,
    site: str = "bazos.sk",
    subcategory: str = "",
    query: str = "",
    location: str = "",
    radius: int = 25,
    price_from: int | None = None,
    price_to: int | None = None,
    page: int = 0,
) -> str:
    """Build a bazos search URL.

    Args:
        category: Subdomain category slug (e.g. "reality", "auto").
        site: Domain — "bazos.sk" or "bazos.cz".
        subcategory: Path-based subcategory (e.g. "prenajmu/byt", "predam/dom").
        query: Search keyword.
        location: City name or postal code.
        radius: Search radius in km.
        price_from: Minimum price filter.
        price_to: Maximum price filter.
        page: Page number (0-indexed). Each page = 20 listings.
    """
    base = f"https://{category}.{site}"
    offset = page * 20

    # Build path: /{subcategory}/{offset}/
    path_parts: list[str] = []
    if subcategory:
        path_parts.append(subcategory.strip("/"))
    if offset > 0:
        path_parts.append(str(offset))

    path = "/" + "/".join(path_parts) + "/" if path_parts else "/"

    params: dict[str, str | int] = {}
    params["hledat"] = query
    params["hlokalita"] = location
    params["humkreis"] = radius
    params["cenaod"] = price_from if price_from is not None else ""
    params["cenado"] = price_to if price_to is not None else ""
    params["order"] = ""

    return f"{base}{path}?{urlencode(params)}"
