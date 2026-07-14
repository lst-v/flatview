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
from flatview.trends import DaysOnMarketStats, PriceCutStats, PriceStory, TrendSummary
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


def test_render_digest_deals_section(make_listing):
    cheap = make_listing(id=5, title="Najlacnejší", price=80_000, area=50)  # 1600 /m²
    ev = WatchEvents(watch=Watch(name="w"), n_listings=8)
    ev.top_deals = [(cheap, 26.4)]
    ev.stories = {("bazos", "5"): PriceStory(n_cuts=2, total_pct=-12.0, days_tracked=47)}
    ev.stats = {"currency": "EUR", "pm2": {"n": 8, "p50": 2000}}
    html = render_digest([ev], generated_at=GENERATED)

    assert "Top deals right now (1)" in html
    assert "Najlacnejší" in html
    assert "-20%" in html  # 1600 vs median 2000
    assert "2 cuts · -12% total · 47 d tracked" in html  # price story
    assert "<strong>26</strong>" in html  # score
    assert "Score = % below median" in html  # formula legend


def test_drop_story_in_digest_and_text(make_listing):
    dropped = make_listing(id=2, title="Zľava byt", price=90_000)
    ev = WatchEvents(watch=Watch(name="w"), n_listings=3)
    ev.price_drops = [PriceChange(listing=dropped, old_price=100_000, new_price=90_000)]
    ev.stories = {("bazos", "2"): PriceStory(n_cuts=3, total_pct=-18.0, days_tracked=60)}

    html = render_digest([ev], generated_at=GENERATED)
    assert "3 cuts · -18% total · 60 d tracked" in html

    text = render_digest_text([ev])
    assert "[3 cuts · -18% total · 60 d tracked]" in text


def _trend(**overrides):
    defaults = dict(
        period_days=7,
        window_days=30,
        median_pm2_now=2000.0,
        median_pm2_prev=1900.0,
        active_now=57,
        active_prev=61,
        n_new=4,
        n_delisted=2,
        n_drops=3,
        days_on_market=DaysOnMarketStats(n=5, median=12.0),
        cuts=PriceCutStats(n_active=57, n_cut=3, median_cut_pct=-3.2),
        series=[("2026-07-01", 1900.0), ("2026-07-08", 1950.0), ("2026-07-13", 2000.0)],
    )
    defaults.update(overrides)
    return TrendSummary(**defaults)


def test_render_digest_trend_block():
    ev = WatchEvents(watch=Watch(name="w"), n_listings=57, trend=_trend())
    html = render_digest([ev], generated_at=GENERATED)

    assert "Market trend" in html
    assert "+5.3%" in html  # 2000 vs 1900
    assert "7 d ago" in html
    assert "-4" in html  # active listings delta
    assert "Last 7 days: 4 new · 2 delisted · 3 price cuts" in html
    assert "Median days on market (delisted, last 30 d): 12 (n=5)" in html
    assert "3 of 57 active listings (5%)" in html and "-3.2%" in html
    assert "07-01" in html and "07-13" in html  # rolling series

    # Text fallback carries the headline delta.
    text = render_digest_text([ev])
    assert "TREND: median €/m² 2,000 (+5.3% vs 7 d ago)" in text


def test_trend_block_hidden_on_baseline_and_without_comparison():
    baseline = WatchEvents(watch=Watch(name="b"), is_baseline=True, n_listings=5, trend=_trend())
    assert "Market trend" not in render_digest([baseline], generated_at=GENERATED)

    # Young watch: no comparison point yet — block renders without the delta table.
    young = WatchEvents(
        watch=Watch(name="y"),
        n_listings=5,
        trend=_trend(median_pm2_prev=None, active_now=None, active_prev=None, series=[]),
    )
    html = render_digest([young], generated_at=GENERATED)
    assert "Market trend" in html
    assert "7 d ago" not in html


def test_digest_escapes_scraped_fields(make_listing):
    evil = make_listing(
        id=1,
        title="<script>alert(1)</script> byt",
        city="<b>Mesto</b>",
        url="javascript:alert(2)",
    )
    ev = WatchEvents(watch=Watch(name="w"), n_listings=1)
    ev.new = [evil]
    failed = WatchEvents(watch=Watch(name="down"), error="<script>boom</script>")

    html = render_digest([ev, failed], generated_at=GENERATED)
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; byt" in html
    assert "href='javascript:" not in html
    assert "<b>Mesto</b>" not in html
    assert "<script>boom" not in html


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
