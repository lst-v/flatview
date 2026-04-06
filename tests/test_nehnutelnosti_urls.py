from b_scrape.nehnutelnosti_urls import build_nehnutelnosti_url


def test_basic_url():
    url = build_nehnutelnosti_url()
    assert url == "https://www.nehnutelnosti.sk/vysledky"


def test_subcategory_mapping():
    url = build_nehnutelnosti_url(subcategory="predam/byt")
    assert "/byty/" in url
    assert url.endswith("/predaj")


def test_room_query_override():
    url = build_nehnutelnosti_url(query="2 izbový", subcategory="predam/byt")
    assert "/2-izbove-byty/" in url
    assert "/byty/" not in url


def test_3_room_query():
    url = build_nehnutelnosti_url(query="3 izbový byt", subcategory="predam/byt")
    assert "/3-izbove-byty/" in url


def test_garsonka_query():
    url = build_nehnutelnosti_url(query="garsónka", subcategory="predam/byt")
    assert "/garsonky/" in url


def test_location_slugified():
    url = build_nehnutelnosti_url(location="Bratislava", subcategory="predam/byt")
    assert "/bratislava/" in url


def test_location_diacritics_stripped():
    url = build_nehnutelnosti_url(location="Košice", subcategory="predam/byt")
    assert "/kosice/" in url


def test_url_segment_order():
    """Order must be: property / location / transaction."""
    url = build_nehnutelnosti_url(
        query="2 izbový", subcategory="predam/byt", location="Michalovce"
    )
    parts = url.split("/vysledky/")[1].split("/")
    assert parts[0] == "2-izbove-byty"
    assert parts[1] == "michalovce"
    assert parts[2] == "predaj"


def test_pagination_page_1():
    url = build_nehnutelnosti_url(page=1)
    assert "page=" not in url


def test_pagination_page_2():
    url = build_nehnutelnosti_url(page=2)
    assert "?page=2" in url


def test_price_params():
    url = build_nehnutelnosti_url(price_from=50000, price_to=200000)
    assert "cena-od=50000" in url
    assert "cena-do=200000" in url


def test_rental_mapping():
    url = build_nehnutelnosti_url(subcategory="prenajmu/byt")
    assert "/prenajom" in url


def test_dom_property():
    url = build_nehnutelnosti_url(subcategory="predam/dom")
    assert "/domy/" in url
