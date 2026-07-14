from __future__ import annotations

from flatview.dedup import dedupe, find_duplicate_groups, is_duplicate, select_canonical

TITLE = "Vynikajúca lokalita - MASARYKOVÁ - Priestranný 2 izbový byt"


def test_same_source_never_duplicate(make_listing):
    a = make_listing(id=1, title=TITLE, source="bazos")
    b = make_listing(id=2, title=TITLE, source="bazos")
    assert is_duplicate(a, b) is False


def test_city_mismatch_vetoes(make_listing):
    a = make_listing(id=1, title=TITLE, source="bazos", city="Michalovce")
    b = make_listing(id=2, title=TITLE, source="topreality", city="Strážske")
    assert is_duplicate(a, b) is False


def test_attribute_match_with_weak_title(make_listing):
    # Same flat, portals describe it differently — titles only loosely similar.
    a = make_listing(
        id=1, title="2-izbový byt Masarykova ulica", source="bazos", price=108_990, area=59.0
    )
    b = make_listing(
        id=2,
        title="Priestranný 2 izbový byt - Masarykova",
        source="nehnutelnosti",
        price=108_990,
        area=58.9,
    )
    assert is_duplicate(a, b) is True


def test_price_contradiction_vetoes_similar_titles(make_listing):
    # Agencies reuse title templates for different flats.
    a = make_listing(id=1, title=TITLE, source="bazos", price=108_990, area=59)
    b = make_listing(id=2, title=TITLE, source="nehnutelnosti", price=85_000, area=59)
    assert is_duplicate(a, b) is False


def test_area_contradiction_vetoes(make_listing):
    a = make_listing(id=1, title=TITLE, source="bazos", price=108_990, area=59)
    b = make_listing(id=2, title=TITLE, source="nehnutelnosti", price=108_990, area=44)
    assert is_duplicate(a, b) is False


def test_title_only_fallback_when_data_missing(make_listing):
    a = make_listing(id=1, title=TITLE, source="bazos", price=None, area=None)
    b = make_listing(id=2, title=TITLE, source="nehnutelnosti", price=108_990, area=59)
    assert is_duplicate(a, b) is True


def test_agency_template_titles_do_not_merge_different_flats(make_listing):
    # Observed live: same agency, similar template titles, different flats.
    a = make_listing(
        id=1,
        title="SIMI real - 2 izbový byt bez balkóna so zariadením",
        source="bazos",
        price=122_000,
        area=54,
    )
    b = make_listing(
        id=2,
        title="SIMI real - 2 izbový byt s balkónom",
        source="nehnutelnosti",
        price=128_000,
        area=50,
    )
    # Both have data → attributes decide; near-miss titles must not merge them.
    assert is_duplicate(a, b) is False


def test_close_but_unequal_prices_do_not_merge(make_listing):
    # Homogeneous market: two different 52 m² flats priced 1% apart.
    a = make_listing(id=1, title="2 izbový byt", source="bazos", price=109_990, area=51.4)
    b = make_listing(
        id=2,
        title="Pôvodný 2 izbový byt - 52 m2 v Michalovciach",
        source="nehnutelnosti",
        price=111_000,
        area=52.0,
    )
    assert is_duplicate(a, b) is False


def test_generic_short_titles_never_fallback_match(make_listing):
    a = make_listing(id=1, title="2 izbový byt", source="bazos", price=None, area=None)
    b = make_listing(id=2, title="2 izbový byt", source="nehnutelnosti", price=None, area=None)
    assert is_duplicate(a, b) is False


def test_groups_are_transitive(make_listing):
    a = make_listing(id=1, title=TITLE, source="bazos", price=108_990, area=59)
    b = make_listing(id=2, title=TITLE, source="nehnutelnosti", price=108_990, area=59)
    c = make_listing(id=3, title=TITLE, source="topreality", price=108_990, area=59)
    other = make_listing(id=4, title="Iný byt na sídlisku", source="bazos", price=70_000, area=50)

    groups = find_duplicate_groups([a, b, c, other])
    assert len(groups) == 1
    assert {id(l) for l in groups[0]} == {id(a), id(b), id(c)}


def test_canonical_prefers_richest_listing(make_listing):
    rich = make_listing(
        id=1,
        title=TITLE,
        source="bazos",
        price=108_990,
        area=59,
        description="Krásny byt",
        postcode="071 01",
        date="1.7. 2026",
        views=100,
    )
    bare = make_listing(
        id=2,
        title=TITLE,
        source="topreality",
        price=108_990,
        area=59,
        description=None,
        postcode="",
        date="",
        views=None,
    )
    assert select_canonical([bare, rich]) is rich


def test_dedupe_keeps_singletons_and_one_per_group(make_listing):
    a = make_listing(id=1, title=TITLE, source="bazos", price=108_990, area=59)
    b = make_listing(id=2, title=TITLE, source="nehnutelnosti", price=108_990, area=59)
    solo = make_listing(id=3, title="Úplne iný inzerát", source="bazos", price=70_000, area=50)

    unique = dedupe([a, b, solo])
    assert len(unique) == 2
    assert solo in unique
    assert (a in unique) != (b in unique)  # exactly one of the pair survives
