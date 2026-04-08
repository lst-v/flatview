from flatview.topreality_urls import build_topreality_url


def test_basic_url():
    url = build_topreality_url()
    assert "www.topreality.sk/vyhladavanie-nehnutelnosti.html?" in url
    assert "searchType=string" in url
    assert "fromForm=1" in url


def test_subcategory_mapping():
    url = build_topreality_url(subcategory="predam/byt")
    assert "form=1" in url    # Predám
    assert "type%5B%5D=103" in url or "type[]=103" in url  # 2 izbový byt


def test_rental_mapping():
    url = build_topreality_url(subcategory="prenajmu/dom")
    assert "form=3" in url    # Prenájom
    assert "type%5B%5D=204" in url or "type[]=204" in url  # Rodinný dom


def test_location_id():
    url = build_topreality_url(location_id="d807-Okres Michalovce")
    assert "obec=d807-Okres+Michalovce" in url or "obec=d807-Okres%20Michalovce" in url


def test_query():
    url = build_topreality_url(query="2 izbový byt")
    assert "q=2" in url


def test_price_params():
    url = build_topreality_url(price_from=100000, price_to=500000)
    assert "cena_od=100000" in url
    assert "cena_do=500000" in url


def test_pagination_page_1():
    url = build_topreality_url(page=1)
    assert "/vyhladavanie-nehnutelnosti.html?" in url
    assert "-1.html" not in url


def test_pagination_page_2():
    url = build_topreality_url(page=2)
    assert "/vyhladavanie-nehnutelnosti-2.html?" in url


def test_pagination_page_5():
    url = build_topreality_url(page=5)
    assert "/vyhladavanie-nehnutelnosti-5.html?" in url


def test_no_subcategory():
    url = build_topreality_url()
    assert "form=" not in url.split("fromForm")[0]  # no form param (except fromForm)
    assert "type%5B%5D" not in url and "type[]" not in url


def test_partial_subcategory_transaction_only():
    url = build_topreality_url(subcategory="predam")
    assert "form=1" in url
    assert "type%5B%5D" not in url and "type[]" not in url


def test_unknown_subcategory_ignored():
    url = build_topreality_url(subcategory="unknown/unknown")
    # form and type[] should not appear (except fromForm)
    parts = url.split("fromForm=1")
    assert "form=" not in parts[0]
    assert "type%5B%5D" not in url and "type[]" not in url


def test_all_params_combined():
    url = build_topreality_url(
        query="2 izbový byt",
        subcategory="predam/byt",
        location_id="d807-Okres Michalovce",
        price_from=50000,
        price_to=200000,
        page=2,
    )
    assert "/vyhladavanie-nehnutelnosti-2.html?" in url
    assert "searchType=string" in url
    assert "fromForm=1" in url
    assert "q=2" in url
    assert "form=1" in url
    assert "cena_od=50000" in url
    assert "cena_do=200000" in url
    assert "obec=" in url
