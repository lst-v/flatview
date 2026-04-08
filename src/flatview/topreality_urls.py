from __future__ import annotations

from urllib.parse import urlencode

# form select: transaction type
TRANSACTION_MAP: dict[str, str] = {
    "predam": "1",     # Predám
    "prenajmu": "3",   # Prenájom
}

# type[] select: property type
PROPERTY_TYPE_MAP: dict[str, str] = {
    "byt": "103",       # 2 izbový byt (generic apartment)
    "dom": "204",       # Rodinný dom
    "pozemok": "802",   # Pozemok pre rodinné domy
    "priestor": "401",  # Kancelárie
}


def resolve_location(location: str, client: object | None = None) -> str:
    """Resolve a city/district name to a topreality location ID via AJAX lookup.

    Returns the ID string (e.g. 'd807-Okres Michalovce') or empty string.
    """
    if not location:
        return ""
    try:
        import requests

        resp = requests.get(
            "https://www.topreality.sk/user/new_estate/searchAjax.php",
            params={"term": location},
            headers={"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        # Find first match containing the location name
        loc_lower = location.lower()
        for item in data:
            if loc_lower in item.get("name", "").lower():
                return item["id"]
    except Exception:
        pass
    return ""


def build_topreality_url(
    query: str = "",
    subcategory: str = "",
    location_id: str = "",
    price_from: int | None = None,
    price_to: int | None = None,
    page: int = 1,
) -> str:
    if page >= 2:
        path = f"/vyhladavanie-nehnutelnosti-{page}.html"
    else:
        path = "/vyhladavanie-nehnutelnosti.html"

    params: dict[str, str | int] = {
        "searchType": "string",
        "fromForm": "1",
    }

    if query:
        params["q"] = query

    if subcategory:
        parts = subcategory.strip("/").split("/")
        if parts:
            form_val = TRANSACTION_MAP.get(parts[0])
            if form_val:
                params["form"] = form_val
        if len(parts) >= 2:
            type_val = PROPERTY_TYPE_MAP.get(parts[1])
            if type_val:
                params["type[]"] = type_val

    if location_id:
        params["obec"] = location_id
    if price_from is not None:
        params["cena_od"] = price_from
    if price_to is not None:
        params["cena_do"] = price_to

    return f"https://www.topreality.sk{path}?{urlencode(params)}"
