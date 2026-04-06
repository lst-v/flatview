import json

from flatview.nehnutelnosti_parser import (
    _extract_jsonld,
    _parse_item,
    parse_nehnutelnosti_listings,
    parse_nehnutelnosti_total_count,
)


def _make_jsonld_html(graph_items, num_items=None):
    """Build minimal HTML with JSON-LD embedded in RSC push chunks."""
    item_list = {
        "@type": "ItemList",
        "itemListElement": [{"item": it} for it in graph_items],
    }
    if num_items is not None:
        item_list["numberOfItems"] = num_items

    data = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "SearchResultsPage",
                "mainEntity": item_list,
            }
        ],
    }
    # Escape for JS string literal
    raw = json.dumps(data).replace("\\", "\\\\").replace('"', '\\"')
    return f'<html><head><script>self.__next_f.push([1,"{raw}"])</script></head><body></body></html>'


SAMPLE_ITEM = {
    "name": "2-izbový byt Michalovce",
    "priceSpecification": {"price": 115000, "priceCurrency": "EUR"},
    "floorSize": {"value": 46},
    "url": "https://www.nehnutelnosti.sk/detail/abc123/2-izbovy-byt",
}


# --- _extract_jsonld tests ---


def test_extract_jsonld_basic():
    html = _make_jsonld_html([SAMPLE_ITEM])
    data = _extract_jsonld(html)
    assert data is not None
    assert "@graph" in data


def test_extract_jsonld_no_scripts():
    data = _extract_jsonld("<html><body>No scripts</body></html>")
    assert data is None


# --- _parse_item tests ---


def test_parse_item_all_fields():
    listing = _parse_item(SAMPLE_ITEM)
    assert listing is not None
    assert listing.title == "2-izbový byt Michalovce"
    assert listing.price == 115000.0
    assert listing.currency == "EUR"
    assert listing.area == 46.0
    assert listing.source == "nehnutelnosti"
    assert "abc123" in str(listing.id)


def test_parse_item_zero_price():
    item = {**SAMPLE_ITEM, "priceSpecification": {"price": 0, "priceCurrency": "EUR"}}
    listing = _parse_item(item)
    assert listing.price is None


def test_parse_item_area_one():
    item = {**SAMPLE_ITEM, "floorSize": {"value": 1}}
    listing = _parse_item(item)
    assert listing.area is None


def test_parse_item_no_area():
    item = {k: v for k, v in SAMPLE_ITEM.items() if k != "floorSize"}
    listing = _parse_item(item)
    assert listing.area is None


def test_parse_item_no_name():
    item = {k: v for k, v in SAMPLE_ITEM.items() if k != "name"}
    assert _parse_item(item) is None


# --- parse_nehnutelnosti_listings tests ---


def test_parse_listings_from_jsonld():
    html = _make_jsonld_html([SAMPLE_ITEM])
    listings = parse_nehnutelnosti_listings(html)
    assert len(listings) == 1
    assert listings[0].title == "2-izbový byt Michalovce"


def test_parse_listings_multiple():
    item2 = {**SAMPLE_ITEM, "name": "3-izbový byt", "priceSpecification": {"price": 200000, "priceCurrency": "EUR"}}
    html = _make_jsonld_html([SAMPLE_ITEM, item2])
    listings = parse_nehnutelnosti_listings(html)
    assert len(listings) == 2


def test_parse_listings_empty_graph():
    html = _make_jsonld_html([])
    listings = parse_nehnutelnosti_listings(html)
    assert listings == []


def test_parse_listings_no_jsonld():
    listings = parse_nehnutelnosti_listings("<html><body>Nothing</body></html>")
    assert listings == []


# --- parse_nehnutelnosti_total_count tests ---


def test_total_count_from_jsonld():
    html = _make_jsonld_html([SAMPLE_ITEM], num_items=42)
    assert parse_nehnutelnosti_total_count(html) == 42


def test_total_count_fallback_regex():
    html = "<html><body>(42 inzerátov)</body></html>"
    assert parse_nehnutelnosti_total_count(html) == 42


def test_total_count_none():
    assert parse_nehnutelnosti_total_count("<html><body>Nothing</body></html>") is None
