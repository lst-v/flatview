from b_scrape.models import Listing, SearchResult


def test_listing_defaults():
    l = Listing(
        title="Test", price=100.0, currency="EUR",
        city="X", postcode="000", date="1.1.2026", url="http://x",
    )
    assert l.views is None
    assert l.id is None
    assert l.source == "bazos"
    assert l.area is None


def test_listing_equality():
    kwargs = dict(title="A", price=1.0, currency="EUR", city="X", postcode="0", date="d", url="u")
    assert Listing(**kwargs) == Listing(**kwargs)


def test_search_result_defaults():
    sr = SearchResult()
    assert sr.listings == []
    assert sr.total_count is None
    assert sr.site == "bazos.sk"
