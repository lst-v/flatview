from b_scrape.display import _find_duplicates


def test_no_duplicates_single_source(make_listing, make_search_result):
    listings = [make_listing(title="Byt A"), make_listing(title="Byt B")]
    results = [make_search_result(listings=listings)]
    assert _find_duplicates(results) == set()


def test_exact_duplicate_cross_source(make_listing, make_search_result):
    bazos = make_listing(title="Predaj 2 izbového bytu - ELITE PARK", source="bazos")
    neh = make_listing(title="Predaj 2 izbového bytu - ELITE PARK", source="nehnutelnosti")
    results = [
        make_search_result(listings=[bazos]),
        make_search_result(listings=[neh], site="nehnutelnosti.sk"),
    ]
    dups = _find_duplicates(results)
    assert id(bazos) in dups
    assert id(neh) in dups


def test_fuzzy_duplicate_above_threshold(make_listing, make_search_result):
    bazos = make_listing(title="MASARYKOVÁ - Priestranný - 2 izbový byt - Čiastočná rekonštr", source="bazos")
    neh = make_listing(
        title="MASARYKOVÁ - Priestranný - 2 izbový byt - Čiastočná rekonštrukcia - Kompletne zariadený",
        source="nehnutelnosti",
    )
    results = [
        make_search_result(listings=[bazos]),
        make_search_result(listings=[neh], site="nehnutelnosti.sk"),
    ]
    dups = _find_duplicates(results)
    assert id(bazos) in dups
    assert id(neh) in dups


def test_below_threshold_not_flagged(make_listing, make_search_result):
    bazos = make_listing(title="Pekný byt na predaj", source="bazos")
    neh = make_listing(title="ELITE PARK novostavba", source="nehnutelnosti")
    results = [
        make_search_result(listings=[bazos]),
        make_search_result(listings=[neh], site="nehnutelnosti.sk"),
    ]
    dups = _find_duplicates(results)
    assert len(dups) == 0


def test_empty_listings(make_search_result):
    results = [make_search_result(listings=[]), make_search_result(listings=[], site="nehnutelnosti.sk")]
    assert _find_duplicates(results) == set()
