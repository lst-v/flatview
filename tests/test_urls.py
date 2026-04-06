from b_scrape.urls import build_search_url


def test_basic_url():
    url = build_search_url(category="reality", site="bazos.sk")
    assert url.startswith("https://reality.bazos.sk/")
    assert "hledat=" in url


def test_subcategory_in_path():
    url = build_search_url(category="reality", subcategory="predam/byt")
    assert "/predam/byt/" in url


def test_pagination_offset():
    url = build_search_url(category="reality", page=3)
    assert "/60/" in url


def test_page_zero_no_offset():
    url = build_search_url(category="reality", page=0)
    assert "/0/" not in url


def test_price_filters():
    url = build_search_url(category="reality", price_from=50000, price_to=150000)
    assert "cenaod=50000" in url
    assert "cenado=150000" in url


def test_cz_site():
    url = build_search_url(category="reality", site="bazos.cz")
    assert "reality.bazos.cz" in url


def test_query_and_location_encoded():
    url = build_search_url(category="reality", query="2 izbový", location="Michalovce")
    assert "hledat=2+izbov" in url
    assert "hlokalita=Michalovce" in url


def test_default_radius():
    url = build_search_url(category="reality")
    assert "humkreis=25" in url


def test_custom_radius():
    url = build_search_url(category="reality", radius=0)
    assert "humkreis=0" in url


def test_subcategory_with_pagination():
    url = build_search_url(category="reality", subcategory="predam/byt", page=2)
    assert "/predam/byt/40/" in url
