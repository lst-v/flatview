from __future__ import annotations

import pytest

from flatview.models import Listing, SearchResult


@pytest.fixture
def make_listing():
    """Factory fixture for Listing objects with sensible defaults."""

    def _make(**overrides):
        defaults = dict(
            title="2-izbový byt Michalovce",
            price=120000.0,
            currency="EUR",
            city="Michalovce",
            postcode="071 01",
            date="1.4. 2026",
            url="https://reality.bazos.sk/inzerat/12345/test.php",
            views=42,
            id=12345,
            source="bazos",
            area=55.0,
        )
        defaults.update(overrides)
        return Listing(**defaults)

    return _make


@pytest.fixture
def make_search_result():
    """Factory fixture for SearchResult objects."""

    def _make(listings=None, **overrides):
        defaults = dict(
            listings=listings or [],
            total_count=None,
            query="2 izbový byt",
            category="reality",
            location="Michalovce",
            site="bazos.sk",
        )
        defaults.update(overrides)
        return SearchResult(**defaults)

    return _make
