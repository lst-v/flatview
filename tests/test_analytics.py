from __future__ import annotations

import pytest

from flatview.analytics import (
    annotate_segments,
    classify_segment,
    compute_percentiles,
    compute_stats,
    flag_outliers_iqr,
    price_per_m2,
    stats_by_segment,
)


def test_percentiles_basic():
    pcts = compute_percentiles([10, 20, 30, 40, 50])
    assert pcts[50] == pytest.approx(30.0)
    assert pcts[25] == pytest.approx(20.0)
    assert pcts[75] == pytest.approx(40.0)


def test_percentiles_empty():
    assert compute_percentiles([]) == {}


def test_percentiles_single():
    pcts = compute_percentiles([42])
    assert pcts[50] == 42
    assert pcts[10] == 42
    assert pcts[90] == 42


def test_price_per_m2(make_listing):
    assert price_per_m2(make_listing(price=120_000, area=60)) == 2000.0
    assert price_per_m2(make_listing(price=None, area=60)) is None
    assert price_per_m2(make_listing(price=100, area=None)) is None
    assert price_per_m2(make_listing(price=100, area=0)) is None


def test_compute_stats_includes_percentiles(make_listing):
    listings = [
        make_listing(price=p, area=50) for p in (80_000, 100_000, 120_000, 150_000, 200_000)
    ]
    stats = compute_stats(listings)
    assert stats["price"]["n"] == 5
    assert "p10" in stats["price"]
    assert "p90" in stats["price"]
    assert stats["pm2"]["n"] == 5


def test_iqr_outlier_below_threshold(make_listing):
    # Fewer than 4 listings — no outlier detection.
    listings = [make_listing(price=p, area=50) for p in (100_000, 200_000, 300_000)]
    flagged, n = flag_outliers_iqr(listings)
    assert flagged == 0
    assert n == 3


def test_iqr_outlier_detection(make_listing):
    prices = [100_000, 105_000, 110_000, 115_000, 120_000, 125_000, 130_000]
    listings = [make_listing(price=p, area=50, title=f"t{p}") for p in prices]
    extreme = make_listing(price=5_000_000, area=50, title="penthouse")
    listings.append(extreme)
    flagged, n = flag_outliers_iqr(listings)
    assert flagged >= 1
    assert n == 8
    assert extreme.is_outlier


def test_segment_new_build(make_listing):
    l = make_listing(title="Predám 3i byt - NOVOSTAVBA Slnečnice")
    assert classify_segment(l) == "new"


def test_segment_resale_panel(make_listing):
    l = make_listing(title="3-izbový byt panelák Petržalka")
    assert classify_segment(l) == "resale"


def test_segment_po_rekonstrukcii_overrides_new(make_listing):
    # Even with a developer mention, "po rekonštrukcii" wins.
    l = make_listing(title="Developer projekt po rekonštrukcii")
    assert classify_segment(l) == "resale"


def test_segment_unknown(make_listing):
    l = make_listing(title="3-izbový byt Košice")
    assert classify_segment(l) == "unknown"


def test_segment_from_description(make_listing):
    l = make_listing(title="3i byt", description="Novostavba s parkovaním, kolaudácia 2025.")
    assert classify_segment(l) == "new"


def test_annotate_segments_mutates(make_listing):
    listings = [
        make_listing(title="Novostavba A"),
        make_listing(title="Panel B"),
        make_listing(title="Random C"),
    ]
    annotate_segments(listings)
    assert [l.segment for l in listings] == ["new", "resale", "unknown"]


def test_stats_by_segment_respects_min_n(make_listing):
    listings = [
        make_listing(title="Novostavba A", price=100_000, area=50),
        make_listing(title="Novostavba B", price=110_000, area=50),
        make_listing(title="Novostavba C", price=120_000, area=50),
        make_listing(title="Random D", price=80_000, area=50),
    ]
    annotate_segments(listings)
    per_seg = stats_by_segment(listings, min_n=3)
    assert "new" in per_seg
    assert "unknown" not in per_seg  # only 1 unknown listing
