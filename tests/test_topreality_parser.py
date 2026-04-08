from flatview.topreality_parser import (
    parse_topreality_listings,
    parse_topreality_total_count,
)


def _make_card(
    id="12345",
    title="2-izbový byt Michalovce",
    url="/detail-r12345.html",
    price="115 000 €",
    city="Michalovce",
    area_floor="46 m²",
    area_building=None,
):
    parts = []
    parts.append(f'<div class="row estate" data-idinz="{id}">')
    parts.append(f'<h2 class="card-title"><a href="{url}">{title}</a></h2>')
    if price is not None:
        parts.append(f'<strong class="price">{price}</strong>')
    if city:
        parts.append(f'<span class="location-city">{city}</span>')
    if area_floor:
        parts.append(f'<span class="area-floor">{area_floor}</span>')
    if area_building:
        parts.append(f'<span class="area-building">{area_building}</span>')
    parts.append("</div>")
    return "\n".join(parts)


def _make_html(cards, total_text=None):
    body = "\n".join(cards)
    header = ""
    if total_text:
        header = f"<div>{total_text}</div>"
    return f"<html><body>{header}{body}</body></html>"


# --- parse_topreality_listings tests ---


def test_parse_single_listing():
    html = _make_html([_make_card()])
    listings = parse_topreality_listings(html)
    assert len(listings) == 1
    l = listings[0]
    assert l.title == "2-izbový byt Michalovce"
    assert l.price == 115000.0
    assert l.currency == "EUR"
    assert l.city == "Michalovce"
    assert l.area == 46.0
    assert l.source == "topreality"
    assert l.id == 12345
    assert l.url == "https://www.topreality.sk/detail-r12345.html"


def test_parse_multiple_listings():
    cards = [
        _make_card(id="1", title="Byt 1"),
        _make_card(id="2", title="Byt 2"),
    ]
    html = _make_html(cards)
    listings = parse_topreality_listings(html)
    assert len(listings) == 2
    assert listings[0].title == "Byt 1"
    assert listings[1].title == "Byt 2"


def test_parse_empty_page():
    html = "<html><body><div>No results</div></body></html>"
    assert parse_topreality_listings(html) == []


def test_parse_price_dohodou():
    html = _make_html([_make_card(price="Dohodou")])
    listings = parse_topreality_listings(html)
    assert listings[0].price is None


def test_parse_price_na_vyziadanie():
    html = _make_html([_make_card(price="Na vyžiadanie")])
    listings = parse_topreality_listings(html)
    assert listings[0].price is None


def test_parse_price_with_spaces():
    html = _make_html([_make_card(price="650 000 €")])
    listings = parse_topreality_listings(html)
    assert listings[0].price == 650000.0


def test_parse_no_price_element():
    html = _make_html([_make_card(price=None)])
    listings = parse_topreality_listings(html)
    assert listings[0].price is None


def test_parse_area_floor():
    html = _make_html([_make_card(area_floor="78.5 m²")])
    listings = parse_topreality_listings(html)
    assert listings[0].area == 78.5


def test_parse_area_fallback_building():
    html = _make_html([_make_card(area_floor=None, area_building="120 m²")])
    listings = parse_topreality_listings(html)
    assert listings[0].area == 120.0


def test_parse_no_area():
    html = _make_html([_make_card(area_floor=None, area_building=None)])
    listings = parse_topreality_listings(html)
    assert listings[0].area is None


def test_parse_area_comma_decimal():
    html = _make_html([_make_card(area_floor="46,5 m²")])
    listings = parse_topreality_listings(html)
    assert listings[0].area == 46.5


def test_parse_relative_url():
    html = _make_html([_make_card(url="/byt-r99.html")])
    listings = parse_topreality_listings(html)
    assert listings[0].url == "https://www.topreality.sk/byt-r99.html"


def test_parse_absolute_url():
    html = _make_html([_make_card(url="https://www.topreality.sk/byt-r99.html")])
    listings = parse_topreality_listings(html)
    assert listings[0].url == "https://www.topreality.sk/byt-r99.html"


def test_parse_listing_id():
    html = _make_html([_make_card(id="9165537")])
    listings = parse_topreality_listings(html)
    assert listings[0].id == 9165537


def test_source_field():
    html = _make_html([_make_card()])
    listings = parse_topreality_listings(html)
    assert all(l.source == "topreality" for l in listings)


def test_postcode_empty():
    html = _make_html([_make_card()])
    listings = parse_topreality_listings(html)
    assert listings[0].postcode == ""


def test_date_empty():
    html = _make_html([_make_card()])
    listings = parse_topreality_listings(html)
    assert listings[0].date == ""


# --- parse_topreality_total_count tests ---


def test_total_count():
    html = _make_html([], total_text="63 775 inzerátov")
    assert parse_topreality_total_count(html) == 63775


def test_total_count_simple():
    html = _make_html([], total_text="42 inzerátov")
    assert parse_topreality_total_count(html) == 42


def test_total_count_none():
    html = "<html><body>Nothing here</body></html>"
    assert parse_topreality_total_count(html) is None
