from __future__ import annotations

import logging

import pytest
import requests

from flatview.models import SearchResult
from flatview.scrape import (
    SearchParams,
    _apply_filters,
    resolve_max_pages,
    scrape,
    scrape_bazos,
)

# --- Minimal bazos-style HTML fixtures ---

TOTAL_COUNT = """
<div class="listainzerat">
  <div class="inzeratynadpis">Zobrazených 1-20 inzerátov z 2</div>
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

PAGE_ONE = TOTAL_COUNT + TWO_CARDS
EMPTY_PAGE = "<html><body><p>No results</p></body></html>"
DETAIL_PAGE = '<div class="maincontent">ok</div><div class="popisdetail">Byt, 65 m², pekný</div>'


class FakeClient:
    """Returns canned responses (or raises canned exceptions) in call order."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.requested: list[str] = []

    def get(self, url: str) -> str:
        self.requested.append(url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# --- resolve_max_pages ---


def test_max_pages_defaults():
    assert resolve_max_pages(SearchParams(query="")) == 0  # browse: all pages
    assert resolve_max_pages(SearchParams(query="byt")) == 1  # query: single page
    assert resolve_max_pages(SearchParams(query="byt", pages=5)) == 5
    assert resolve_max_pages(SearchParams(query="byt", pages=0)) == 0


# --- _apply_filters ---


def test_filters_strict_location(make_listing):
    listings = [make_listing(city="Michalovce"), make_listing(city="Košice")]
    params = SearchParams(location="Michalovce", strict_location=True)
    out = _apply_filters(listings, params, None)
    assert [l.city for l in out] == ["Michalovce"]


def test_filters_zip_normalizes_spaces(make_listing):
    listings = [make_listing(postcode="071 01"), make_listing(postcode="040 01")]
    params = SearchParams(zip_code="07101")
    out = _apply_filters(listings, params, None)
    assert [l.postcode for l in out] == ["071 01"]


def test_filters_title_regex(make_listing):
    import re

    listings = [make_listing(title="Po rekonštrukcii"), make_listing(title="Novostavba")]
    out = _apply_filters(listings, SearchParams(), re.compile("rekonštr", re.IGNORECASE))
    assert [l.title for l in out] == ["Po rekonštrukcii"]


def test_filters_disabled_for_portals_without_data(make_listing):
    listings = [make_listing(city="Košice", postcode="")]
    params = SearchParams(location="Michalovce", strict_location=True, zip_code="07101")
    out = _apply_filters(listings, params, None, strict_location=False, zip_filter=False)
    assert out == listings


# --- scrape_bazos ---


def test_bazos_pagination_stops_on_empty_page():
    client = FakeClient([PAGE_ONE, EMPTY_PAGE, DETAIL_PAGE, DETAIL_PAGE])
    result = scrape_bazos(SearchParams(pages=0), client)

    assert result.total_count == 2
    assert len(result.listings) == 2
    assert len(client.requested) == 4  # 2 pages + 2 detail fetches
    assert result.listings[0].area == 65.0
    assert "65 m²" in (result.listings[0].description or "")


def test_bazos_detail_url_subdomain_fixed():
    client = FakeClient([PAGE_ONE, EMPTY_PAGE, DETAIL_PAGE, DETAIL_PAGE])
    result = scrape_bazos(SearchParams(category="reality", pages=0), client)
    assert all(l.url.startswith("https://reality.bazos.sk/") for l in result.listings)


def test_bazos_detail_fetch_failure_logged_and_skipped(caplog):
    client = FakeClient(
        [
            PAGE_ONE,
            EMPTY_PAGE,
            requests.ConnectionError("boom"),
            DETAIL_PAGE,
        ]
    )
    with caplog.at_level(logging.WARNING, logger="flatview.scrape"):
        result = scrape_bazos(SearchParams(pages=0), client)

    assert len(result.listings) == 2
    assert result.listings[0].area is None  # failed detail fetch skipped
    assert result.listings[1].area == 65.0
    assert any("detail fetch failed" in r.message for r in caplog.records)


def test_bazos_network_error_stops_pagination(caplog):
    client = FakeClient([requests.ConnectionError("offline")])
    with caplog.at_level(logging.ERROR, logger="flatview.scrape"):
        result = scrape_bazos(SearchParams(pages=0), client)

    assert result.listings == []
    assert any("error fetching page" in r.message for r in caplog.records)


def test_drift_warning_on_zero_parsed(caplog):
    client = FakeClient([EMPTY_PAGE])
    with caplog.at_level(logging.WARNING, logger="flatview.scrape"):
        scrape_bazos(SearchParams(pages=1), client)

    assert any("page structure may have changed" in r.message for r in caplog.records)


# --- scrape() dispatch ---


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("bazos", ["bazos"]),
        ("nehnutelnosti", ["nehnutelnosti"]),
        ("topreality", ["topreality"]),
        ("all", ["bazos", "nehnutelnosti", "topreality"]),
    ],
)
def test_scrape_dispatch(monkeypatch, source, expected):
    def fake(name):
        return lambda params, client: SearchResult(site=name)

    monkeypatch.setattr("flatview.scrape.scrape_bazos", fake("bazos"))
    monkeypatch.setattr("flatview.scrape.scrape_nehnutelnosti", fake("nehnutelnosti"))
    monkeypatch.setattr("flatview.scrape.scrape_topreality", fake("topreality"))

    results = scrape(SearchParams(source=source), client=FakeClient([]))
    assert [r.site for r in results] == expected
