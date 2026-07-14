from __future__ import annotations

from datetime import datetime

import pytest

from flatview.digest import (
    digest_subject,
    has_events,
    render_digest,
    render_digest_text,
    write_digest,
)
from flatview.track import DelistedInfo, PriceChange, WatchEvents
from flatview.watches import Watch

GENERATED = datetime(2026, 7, 13, 7, 30)


@pytest.fixture
def events(make_listing):
    new = make_listing(id=1, title="Nový byt", price=100_000, area=50)
    dropped = make_listing(id=2, title="Zľava byt", price=90_000, area=50)
    bargain = make_listing(id=3, title="Lacný byt", price=40_000, area=50)
    bargain.is_outlier = True
    bargain.outlier_side = "bargain"

    ev = WatchEvents(watch=Watch(name="mi-2izb"), n_listings=12)
    ev.new = [new]
    ev.price_drops = [PriceChange(listing=dropped, old_price=100_000, new_price=90_000)]
    ev.delisted = [
        DelistedInfo(
            source="bazos",
            listing_key="9",
            title="Predaný byt",
            url="https://example.com/9",
            last_price=120_000,
            first_matched="2026-07-01",
            last_matched="2026-07-10",
        )
    ]
    ev.bargains = [bargain]
    ev.fence = (1200.0, 2600.0)
    ev.stats = {
        "currency": "EUR",
        "n_total": 12,
        "price": {"n": 12, "p25": 90_000, "p50": 100_000, "p75": 110_000},
        "pm2": {"n": 10, "p25": 1800, "p50": 2000, "p75": 2200},
    }
    return [ev]


def test_has_events(events, make_listing):
    assert has_events(events) is True

    quiet = WatchEvents(watch=Watch(name="quiet"), n_listings=5)
    assert has_events([quiet]) is False

    failed = WatchEvents(watch=Watch(name="down"), error="offline")
    assert has_events([failed]) is True

    # Bargains alone don't retrigger email — they persist run to run.
    only_bargains = WatchEvents(watch=Watch(name="b"), bargains=[make_listing(id=1)])
    assert has_events([only_bargains]) is False


def test_digest_subject_counts(events):
    assert digest_subject(events) == "flatview: 1 new, 1 drop, 1 delisted (mi-2izb)"


def test_digest_subject_no_changes():
    quiet = WatchEvents(watch=Watch(name="q"), n_listings=3)
    assert digest_subject([quiet]) == "flatview: no changes (q)"


def test_render_digest_sections(events):
    html = render_digest(events, generated_at=GENERATED)

    assert "mi-2izb" in html
    assert "New listings (1)" in html
    assert "Nový byt" in html
    assert "Price drops (1)" in html
    assert "-10.0%" in html
    assert "Delisted (1)" in html
    assert "Predaný byt" in html
    assert "Potential bargains (1)" in html
    assert "1,200" in html and "2,600" in html  # fence values
    assert "Market snapshot" in html
    assert "2026-07-13 07:30" in html
    assert "<script" not in html.lower()  # email-safe


def test_render_digest_unique_count(make_listing):
    ev = WatchEvents(watch=Watch(name="w"), n_listings=10, n_unique=7)
    html = render_digest([ev], generated_at=GENERATED)
    assert "10 listings (7 unique" in html

    same = WatchEvents(watch=Watch(name="w2"), n_listings=5, n_unique=5)
    html = render_digest([same], generated_at=GENERATED)
    assert "5 listings" in html
    assert "unique" not in html.split("w2")[1].split("</p>")[0]


def test_render_digest_cheapest_section(make_listing):
    cheap = make_listing(id=5, title="Najlacnejší", price=80_000, area=50)  # 1600 /m²
    ev = WatchEvents(watch=Watch(name="w"), n_listings=8)
    ev.cheapest = [cheap]
    ev.stats = {"currency": "EUR", "pm2": {"n": 8, "p50": 2000}}
    html = render_digest([ev], generated_at=GENERATED)

    assert "Lowest €/m² right now (1)" in html
    assert "Najlacnejší" in html
    assert "-20%" in html  # 1600 vs median 2000


def test_render_digest_error_and_baseline(make_listing):
    failed = WatchEvents(watch=Watch(name="down"), error="connection refused")
    baseline = WatchEvents(watch=Watch(name="fresh"), is_baseline=True, n_listings=4)
    html = render_digest([failed, baseline], generated_at=GENERATED)

    assert "Run failed:" in html
    assert "connection refused" in html
    assert "Baseline run" in html


def test_render_digest_text(events):
    text = render_digest_text(events)
    assert "mi-2izb: 12 listings, 1 new, 1 price drops, 1 delisted" in text
    assert "NEW: Nový byt" in text
    assert "DROP: Zľava byt" in text
    assert "DELISTED: Predaný byt" in text


def test_write_digest_creates_files(tmp_path, events):
    html = render_digest(events, generated_at=GENERATED)
    path = write_digest(html, tmp_path / "digests", GENERATED)

    assert path.name == "digest_2026-07-13_0730.html"
    assert path.exists()
    latest = tmp_path / "digests" / "latest.html"
    assert latest.exists()
    assert latest.read_text() == path.read_text()
    assert path.read_text().startswith("<!doctype html>")
