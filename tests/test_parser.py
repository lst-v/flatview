import pytest

from b_scrape.parser import AREA_RE, _parse_price, parse_detail_area, parse_listings, parse_total_count


# --- Minimal HTML fixtures ---

LISTING_CARD = """
<div class="inzeraty inzeratyflex">
  <div class="inzeratynadpis">
    <h2 class="nadpis"><a href="/inzerat/12345/test-byt.php">Pekný 2-izbový byt</a></h2>
    [1.4. 2026]
  </div>
  <div class="inzeratycena">115 000 €</div>
  <div class="inzeratylok">
    Michalovce<br>071 01
  </div>
  <div class="inzeratyview">156</div>
</div>
"""

TWO_CARDS = """
<div class="inzeraty inzeratyflex">
  <div class="inzeratynadpis">
    <h2 class="nadpis"><a href="/inzerat/111/first.php">First</a></h2>[1.1. 2026]
  </div>
  <div class="inzeratycena">100 000 €</div>
  <div class="inzeratylok">Bratislava<br>811 01</div>
</div>
<div class="inzeraty inzeratyflex">
  <div class="inzeratynadpis">
    <h2 class="nadpis"><a href="/inzerat/222/second.php">Second</a></h2>[2.2. 2026]
  </div>
  <div class="inzeratycena">200 000 €</div>
  <div class="inzeratylok">Košice<br>040 01</div>
</div>
"""

EMPTY_PAGE = "<html><body><p>No results</p></body></html>"

NO_PRICE_CARD = """
<div class="inzeraty inzeratyflex">
  <div class="inzeratynadpis">
    <h2 class="nadpis"><a href="/inzerat/999/wanted.php">Hľadám byt</a></h2>[5.5. 2026]
  </div>
  <div class="inzeratycena">Dohodou</div>
  <div class="inzeratylok">Nitra<br>949 01</div>
</div>
"""

TOTAL_COUNT_HTML = """
<div class="listainzerat">
  <div class="inzeratynadpis">Zobrazených 1-20 inzerátov z 84</div>
</div>
"""


# --- parse_listings tests ---


def test_parse_single_listing():
    listings = parse_listings(LISTING_CARD, site="bazos.sk")
    assert len(listings) == 1
    l = listings[0]
    assert l.title == "Pekný 2-izbový byt"
    assert l.price == 115000.0
    assert l.currency == "EUR"
    assert l.city == "Michalovce"
    assert l.postcode == "071 01"
    assert l.date == "1.4. 2026"
    assert l.id == 12345
    assert l.views == 156


def test_parse_multiple_listings():
    listings = parse_listings(TWO_CARDS, site="bazos.sk")
    assert len(listings) == 2
    assert listings[0].title == "First"
    assert listings[1].title == "Second"


def test_parse_empty_page():
    assert parse_listings(EMPTY_PAGE) == []


def test_parse_no_price():
    listings = parse_listings(NO_PRICE_CARD, site="bazos.sk")
    assert len(listings) == 1
    assert listings[0].price is None


def test_parse_cz_site():
    card = LISTING_CARD.replace("115 000 €", "2 500 000 Kč")
    listings = parse_listings(card, site="bazos.cz")
    assert listings[0].currency == "CZK"


def test_parse_missing_nadpis():
    html = '<div class="inzeraty inzeratyflex"><div>No title here</div></div>'
    assert parse_listings(html) == []


# --- parse_total_count tests ---


def test_parse_total_count_normal():
    assert parse_total_count(TOTAL_COUNT_HTML) == 84


def test_parse_total_count_thousands():
    html = TOTAL_COUNT_HTML.replace("z 84", "z 1 234")
    assert parse_total_count(html) == 1234


def test_parse_total_count_missing():
    assert parse_total_count(EMPTY_PAGE) is None


# --- parse_detail_area tests ---


def test_parse_area_m2_unicode():
    html = '<div class="maincontent">OK</div><div class="popisdetail">Byt o výmere 65 m² na predaj</div>'
    assert parse_detail_area(html) == 65.0


def test_parse_area_m2_ascii():
    html = '<div class="maincontent">OK</div><div class="popisdetail">Plocha 54m2 s balkónom</div>'
    assert parse_detail_area(html) == 54.0


def test_parse_area_comma_decimal():
    html = '<div class="maincontent">OK</div><div class="popisdetail">72,5 m²</div>'
    assert parse_detail_area(html) == 72.5


def test_parse_area_deleted_listing():
    html = '<div class="maincontent">Inzerát bol vymazaný.</div><div class="popisdetail">65 m²</div>'
    assert parse_detail_area(html) is None


def test_parse_area_tiny_value():
    html = '<div class="maincontent">OK</div><div class="popisdetail">1 m²</div>'
    assert parse_detail_area(html) is None


def test_parse_area_no_description():
    html = "<html><body><p>No popisdetail here</p></body></html>"
    assert parse_detail_area(html) is None


def test_parse_area_no_match():
    html = '<div class="maincontent">OK</div><div class="popisdetail">Pekný byt na predaj</div>'
    assert parse_detail_area(html) is None


# --- _parse_price tests ---


def test_price_eur():
    assert _parse_price("89 900 €", "EUR") == (89900.0, "EUR")


def test_price_czk():
    assert _parse_price("2 500 000 Kč", "CZK") == (2500000.0, "CZK")


def test_price_dohodou():
    price, currency = _parse_price("Dohodou", "EUR")
    assert price is None


def test_price_nbsp():
    assert _parse_price("89\xa0900\xa0€", "EUR") == (89900.0, "EUR")


def test_price_no_symbol_uses_default():
    price, currency = _parse_price("150000", "EUR")
    assert price == 150000.0
    assert currency == "EUR"


# --- AREA_RE tests ---


def test_area_regex_m2():
    assert AREA_RE.search("65 m²").group(1) == "65"


def test_area_regex_ascii():
    assert AREA_RE.search("54m2").group(1) == "54"


def test_area_regex_comma():
    assert AREA_RE.search("72,5 m²").group(1) == "72,5"
