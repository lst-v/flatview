from __future__ import annotations

import pytest

from flatview.models import SearchResult
from flatview.scrape import SearchParams
from flatview.storage import open_db
from flatview.track import run_track, run_watch
from flatview.watches import Watch, add_watch


@pytest.fixture
def conn(tmp_path):
    conn = open_db(tmp_path / "test.db")
    yield conn
    conn.close()


@pytest.fixture
def watch(conn):
    w = Watch(name="w1", params=SearchParams(query="byt"))
    add_watch(conn, w)
    return w


def _patch_scrape(monkeypatch, outcome):
    """Patch flatview.track.scrape to return canned results or raise."""

    def fake(params, client=None):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("flatview.track.scrape", fake)


def _result(listings, error=None):
    return [SearchResult(listings=listings, site="bazos.sk", error=error)]


# --- baseline & NEW detection ---


def test_baseline_run_suppresses_new(conn, watch, make_listing, monkeypatch):
    _patch_scrape(monkeypatch, _result([make_listing(id=1), make_listing(id=2)]))
    ev = run_watch(conn, None, watch, observed_at="2026-07-01")

    assert ev.is_baseline is True
    assert ev.new == []
    assert ev.n_listings == 2

    status, n_listings, n_new = conn.execute(
        "SELECT status, n_listings, n_new FROM watch_runs"
    ).fetchone()
    assert (status, n_listings, n_new) == ("ok", 2, 0)
    assert conn.execute("SELECT COUNT(*) FROM watch_listings").fetchone()[0] == 2


def test_second_run_detects_new(conn, watch, make_listing, monkeypatch):
    _patch_scrape(monkeypatch, _result([make_listing(id=1)]))
    run_watch(conn, None, watch, observed_at="2026-07-01")

    _patch_scrape(monkeypatch, _result([make_listing(id=1), make_listing(id=2, title="Nový")]))
    ev = run_watch(conn, None, watch, observed_at="2026-07-02")

    assert ev.is_baseline is False
    assert [l.title for l in ev.new] == ["Nový"]


# --- price events ---


def test_price_drop_detected_once(conn, watch, make_listing, monkeypatch):
    _patch_scrape(monkeypatch, _result([make_listing(id=1, price=100_000)]))
    run_watch(conn, None, watch, observed_at="2026-07-01")

    _patch_scrape(monkeypatch, _result([make_listing(id=1, price=90_000)]))
    ev2 = run_watch(conn, None, watch, observed_at="2026-07-02")
    assert len(ev2.price_drops) == 1
    assert ev2.price_drops[0].old_price == 100_000
    assert ev2.price_drops[0].new_price == 90_000
    assert ev2.price_drops[0].pct == pytest.approx(-10.0)

    # Unchanged price on the next run: not re-reported.
    _patch_scrape(monkeypatch, _result([make_listing(id=1, price=90_000)]))
    ev3 = run_watch(conn, None, watch, observed_at="2026-07-03")
    assert ev3.price_drops == []


def test_price_increase_detected(conn, watch, make_listing, monkeypatch):
    _patch_scrape(monkeypatch, _result([make_listing(id=1, price=100_000)]))
    run_watch(conn, None, watch, observed_at="2026-07-01")

    _patch_scrape(monkeypatch, _result([make_listing(id=1, price=120_000)]))
    ev = run_watch(conn, None, watch, observed_at="2026-07-02")
    assert len(ev.price_increases) == 1
    assert ev.price_drops == []


# --- delisting ---


def test_delist_only_after_grace_days(conn, watch, make_listing, monkeypatch):
    _patch_scrape(monkeypatch, _result([make_listing(id=1), make_listing(id=2, title="Zmizne")]))
    run_watch(conn, None, watch, observed_at="2026-07-01")

    # Next day: id=2 missing, but within the 2-day grace window.
    _patch_scrape(monkeypatch, _result([make_listing(id=1)]))
    ev = run_watch(conn, None, watch, observed_at="2026-07-02")
    assert ev.delisted == []

    # Day 4: last_matched (07-01) is now older than the cutoff (07-02).
    ev = run_watch(conn, None, watch, observed_at="2026-07-04")
    assert [d.listing_key for d in ev.delisted] == ["2"]
    assert ev.delisted[0].title == "Zmizne"

    delisted_at = conn.execute(
        "SELECT delisted_at FROM watch_listings WHERE listing_key='2'"
    ).fetchone()[0]
    assert delisted_at == "2026-07-04"


def test_reappearance_clears_delisted(conn, watch, make_listing, monkeypatch):
    _patch_scrape(monkeypatch, _result([make_listing(id=1), make_listing(id=2)]))
    run_watch(conn, None, watch, observed_at="2026-07-01")
    _patch_scrape(monkeypatch, _result([make_listing(id=1)]))
    run_watch(conn, None, watch, observed_at="2026-07-04")  # id=2 delisted

    _patch_scrape(monkeypatch, _result([make_listing(id=1), make_listing(id=2)]))
    ev = run_watch(conn, None, watch, observed_at="2026-07-05")

    assert ev.new == []  # reappearance is not "new"
    assert ev.delisted == []
    delisted_at = conn.execute(
        "SELECT delisted_at FROM watch_listings WHERE listing_key='2'"
    ).fetchone()[0]
    assert delisted_at is None


def test_no_delist_on_empty_run(conn, watch, make_listing, monkeypatch):
    _patch_scrape(monkeypatch, _result([make_listing(id=1)]))
    run_watch(conn, None, watch, observed_at="2026-07-01")

    _patch_scrape(monkeypatch, _result([]))
    ev = run_watch(conn, None, watch, observed_at="2026-07-10")

    assert ev.delisted == []
    assert (
        conn.execute("SELECT delisted_at FROM watch_listings WHERE listing_key='1'").fetchone()[0]
        is None
    )
    status = conn.execute("SELECT status FROM watch_runs ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert status == "empty"


# --- error handling ---


def test_scrape_exception_records_error(conn, watch, make_listing, monkeypatch):
    _patch_scrape(monkeypatch, RuntimeError("boom"))
    ev = run_watch(conn, None, watch, observed_at="2026-07-01")

    assert ev.error == "boom"
    status, error = conn.execute("SELECT status, error FROM watch_runs").fetchone()
    assert (status, error) == ("error", "boom")
    assert conn.execute("SELECT COUNT(*) FROM watch_listings").fetchone()[0] == 0


def test_fetch_errors_with_no_listings_is_error(conn, watch, make_listing, monkeypatch):
    _patch_scrape(monkeypatch, _result([], error="connection refused"))
    ev = run_watch(conn, None, watch, observed_at="2026-07-01")

    assert ev.error == "connection refused"
    assert conn.execute("SELECT status FROM watch_runs").fetchone()[0] == "error"


def test_error_run_does_not_delist(conn, watch, make_listing, monkeypatch):
    _patch_scrape(monkeypatch, _result([make_listing(id=1)]))
    run_watch(conn, None, watch, observed_at="2026-07-01")

    _patch_scrape(monkeypatch, _result([], error="offline"))
    ev = run_watch(conn, None, watch, observed_at="2026-07-10")

    assert ev.error == "offline"
    assert ev.delisted == []
    assert (
        conn.execute("SELECT delisted_at FROM watch_listings WHERE listing_key='1'").fetchone()[0]
        is None
    )


# --- dry run ---


def test_dry_run_writes_nothing(conn, watch, make_listing, monkeypatch):
    _patch_scrape(monkeypatch, _result([make_listing(id=1)]))
    run_watch(conn, None, watch, observed_at="2026-07-01")  # real baseline

    _patch_scrape(monkeypatch, _result([make_listing(id=1), make_listing(id=2, title="Nový")]))
    ev = run_watch(conn, None, watch, observed_at="2026-07-02", dry_run=True)

    assert [l.title for l in ev.new] == ["Nový"]  # events still detected
    assert conn.execute("SELECT COUNT(*) FROM watch_runs").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM watch_listings").fetchone()[0] == 1


def test_cross_posted_new_listing_suppressed(conn, watch, make_listing, monkeypatch):
    flat = dict(title="MASARYKOVÁ - Priestranný 2 izbový byt", price=108_990, area=59.0)
    filler = [make_listing(id=i, price=90_000 + i * 1000, title=f"iný {i}") for i in (10, 11)]

    # Baseline: flat tracked on bazos.
    _patch_scrape(monkeypatch, _result([make_listing(id=1, source="bazos", **flat), *filler]))
    run_watch(conn, None, watch, observed_at="2026-07-01")

    # Next day the agency cross-posts the same flat to nehnutelnosti.
    cross_post = make_listing(id=None, source="nehnutelnosti", **flat)
    _patch_scrape(
        monkeypatch,
        _result([make_listing(id=1, source="bazos", **flat), cross_post, *filler]),
    )
    ev = run_watch(conn, None, watch, observed_at="2026-07-02")

    assert ev.new == []  # cross-post, not a new flat
    assert ev.n_unique == 3  # 4 listings, flat counted once


def test_flat_debuting_on_two_portals_alerts_once(conn, watch, make_listing, monkeypatch):
    flat = dict(title="Novinka na Okružnej - 2 izbový byt", price=99_000, area=52.0)
    filler = make_listing(id=10, price=90_000, title="iný byt")

    _patch_scrape(monkeypatch, _result([filler]))
    run_watch(conn, None, watch, observed_at="2026-07-01")

    _patch_scrape(
        monkeypatch,
        _result(
            [
                filler,
                make_listing(id=2, source="bazos", **flat),
                make_listing(id=None, source="nehnutelnosti", **flat),
            ]
        ),
    )
    ev = run_watch(conn, None, watch, observed_at="2026-07-02")

    assert len(ev.new) == 1  # one alert for one flat, not two


def test_stats_computed_on_unique_pool(conn, watch, make_listing, monkeypatch):
    flat = dict(title="MASARYKOVÁ - Priestranný 2 izbový byt", price=108_990, area=59.0)
    listings = [
        make_listing(id=1, source="bazos", **flat),
        make_listing(id=None, source="nehnutelnosti", **flat),
        make_listing(id=None, source="topreality", **flat),
        make_listing(id=4, price=90_000, area=50, title="iný byt"),
    ]
    _patch_scrape(monkeypatch, _result(listings))
    ev = run_watch(conn, None, watch, observed_at="2026-07-01")

    assert ev.n_listings == 4
    assert ev.n_unique == 2
    assert ev.stats["price"]["n"] == 2  # the triple-posted flat counts once


def test_custom_iqr_k_changes_flagging(conn, watch, make_listing, monkeypatch):
    # pm2 pool [1000, 2000, 2100, 2200, 3200]: default fences 1700/2500 flag
    # both extremes; k=10 widens the fence so nothing is an outlier.
    listings = [
        make_listing(id=i, title=f"byt {i}", price=p, area=10)
        for i, p in enumerate([10_000, 20_000, 21_000, 22_000, 32_000])
    ]
    _patch_scrape(monkeypatch, _result(listings))
    ev = run_watch(conn, None, watch, observed_at="2026-07-01")
    assert len(ev.bargains) == 1 and len(ev.overpriced) == 1

    ev = run_watch(conn, None, watch, observed_at="2026-07-02", iqr_k=10.0)
    assert ev.bargains == [] and ev.overpriced == []
    assert ev.fence is not None and ev.fence[0] < 1000  # widened fence


def test_trend_populated_after_runs(conn, watch, make_listing, monkeypatch):
    _patch_scrape(monkeypatch, _result([make_listing(id=1, price=100_000, area=50)]))
    ev1 = run_watch(conn, None, watch, observed_at="2026-07-01")
    assert ev1.trend is not None
    assert ev1.trend.median_pm2_prev is None  # nothing existed 7 days ago

    _patch_scrape(monkeypatch, _result([make_listing(id=1, price=90_000, area=50)]))
    ev2 = run_watch(conn, None, watch, observed_at="2026-07-08")

    assert ev2.trend is not None
    assert ev2.trend.median_pm2_now == pytest.approx(1800.0)
    assert ev2.trend.median_pm2_prev == pytest.approx(2000.0)
    assert ev2.trend.pm2_delta_pct == pytest.approx(-10.0)
    assert ev2.trend.n_drops == 1  # this run's drop counts even before it's recorded


def test_dry_run_has_no_trend(conn, watch, make_listing, monkeypatch):
    _patch_scrape(monkeypatch, _result([make_listing(id=1)]))
    run_watch(conn, None, watch, observed_at="2026-07-01")
    ev = run_watch(conn, None, watch, observed_at="2026-07-02", dry_run=True)
    assert ev.trend is None


def test_cheapest_populated(conn, watch, make_listing, monkeypatch):
    listings = [
        make_listing(id=1, price=100_000, area=50, title="expensive"),
        make_listing(id=2, price=80_000, area=50, title="cheap"),
        make_listing(id=3, price=90_000, area=50, title="middle"),
        make_listing(id=4, price=95_000, area=50, title="upper"),
    ]
    _patch_scrape(monkeypatch, _result(listings))
    ev = run_watch(conn, None, watch, observed_at="2026-07-01")

    assert [l.title for l in ev.cheapest] == ["cheap", "middle", "upper", "expensive"]


# --- run_track ---


def test_run_track_ok_exit_code(tmp_path, make_listing, monkeypatch):
    db = tmp_path / "t.db"
    conn = open_db(db)
    add_watch(conn, Watch(name="a"))
    add_watch(conn, Watch(name="b"))
    conn.close()

    _patch_scrape(monkeypatch, _result([make_listing(id=1)]))
    code, events = run_track(db_path=db)
    assert code == 0
    assert [e.watch.name for e in events] == ["a", "b"]


def test_run_track_error_exit_code(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    conn = open_db(db)
    add_watch(conn, Watch(name="a"))
    conn.close()

    _patch_scrape(monkeypatch, RuntimeError("down"))
    code, events = run_track(db_path=db)
    assert code == 1
    assert events[0].error == "down"


def test_run_track_unknown_watch(tmp_path):
    db = tmp_path / "t.db"
    open_db(db).close()
    code, events = run_track(db_path=db, watch_name="nope")
    assert code == 2
    assert events == []


def test_run_track_no_watches(tmp_path):
    db = tmp_path / "t.db"
    open_db(db).close()
    code, events = run_track(db_path=db)
    assert code == 0
    assert events == []
