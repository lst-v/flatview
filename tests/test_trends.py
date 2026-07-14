from __future__ import annotations

import pytest

from flatview.storage import open_db
from flatview.trends import (
    activity_since,
    compute_trend,
    days_on_market_stats,
    price_cut_stats,
    rolling_median_pm2,
    snapshot,
)

WATCH_ID = 1


@pytest.fixture
def conn(tmp_path):
    conn = open_db(tmp_path / "test.db")
    conn.execute("INSERT INTO watches (id, name, created_at) VALUES (1, 'w', '2026-06-01')")
    conn.commit()
    yield conn
    conn.close()


def add_listing(
    conn,
    key,
    *,
    source="bazos",
    area=50.0,
    prices,  # list of (observed_at, price)
    first_matched,
    last_matched,
    delisted_at=None,
):
    conn.execute(
        """INSERT INTO listings (source, listing_key, area, first_seen, last_seen, last_price)
           VALUES (?,?,?,?,?,?)""",
        (source, key, area, first_matched, last_matched, prices[-1][1] if prices else None),
    )
    for observed_at, price in prices:
        conn.execute(
            "INSERT INTO price_history VALUES (?,?,?,?)", (source, key, observed_at, price)
        )
    conn.execute(
        "INSERT INTO watch_listings VALUES (?,?,?,?,?,?)",
        (WATCH_ID, source, key, first_matched, last_matched, delisted_at),
    )
    conn.commit()


def add_run(conn, started_at, *, status="ok", n_new=0, n_delisted=0, n_drops=0):
    conn.execute(
        """INSERT INTO watch_runs
           (watch_id, started_at, status, n_listings, n_new, n_price_drops, n_delisted)
           VALUES (?,?,?,1,?,?,?)""",
        (WATCH_ID, started_at, status, n_new, n_drops, n_delisted),
    )
    conn.commit()


# --- snapshot ---


def test_snapshot_uses_price_as_of_date(conn):
    add_listing(
        conn,
        "1",
        area=50,
        prices=[("2026-07-01", 100_000), ("2026-07-08", 90_000)],
        first_matched="2026-07-01",
        last_matched="2026-07-10",
    )
    median_early, n_early = snapshot(conn, WATCH_ID, "2026-07-05")
    median_late, n_late = snapshot(conn, WATCH_ID, "2026-07-10")

    assert median_early == pytest.approx(2000.0)  # 100k / 50
    assert median_late == pytest.approx(1800.0)  # cut to 90k
    assert n_early == n_late == 1


def test_snapshot_respects_membership_window(conn):
    add_listing(
        conn,
        "1",
        prices=[("2026-07-05", 100_000)],
        first_matched="2026-07-05",
        last_matched="2026-07-10",
    )
    assert snapshot(conn, WATCH_ID, "2026-07-04") == (None, 0)  # not yet matched
    assert snapshot(conn, WATCH_ID, "2026-07-12")[1] == 0  # already gone
    assert snapshot(conn, WATCH_ID, "2026-07-07")[1] == 1


def test_snapshot_collapses_cross_posts(conn):
    # Same flat on two portals: exact price, portal-rounded area.
    add_listing(
        conn,
        "1",
        source="bazos",
        area=51.6,
        prices=[("2026-07-01", 108_990)],
        first_matched="2026-07-01",
        last_matched="2026-07-10",
    )
    add_listing(
        conn,
        "slug-1",
        source="nehnutelnosti",
        area=52.0,
        prices=[("2026-07-01", 108_990)],
        first_matched="2026-07-01",
        last_matched="2026-07-10",
    )
    add_listing(
        conn,
        "2",
        source="bazos",
        area=60.0,
        prices=[("2026-07-01", 120_000)],
        first_matched="2026-07-01",
        last_matched="2026-07-10",
    )
    _, n = snapshot(conn, WATCH_ID, "2026-07-05")
    assert n == 2


def test_snapshot_excludes_placeholder_prices_from_median(conn):
    add_listing(
        conn,
        "1",
        area=50,
        prices=[("2026-07-01", 1.0)],  # "Rezervované" token ad
        first_matched="2026-07-01",
        last_matched="2026-07-10",
    )
    add_listing(
        conn,
        "2",
        area=50,
        prices=[("2026-07-01", 100_000)],
        first_matched="2026-07-01",
        last_matched="2026-07-10",
    )
    median, n = snapshot(conn, WATCH_ID, "2026-07-05")
    assert median == pytest.approx(2000.0)
    assert n == 2  # placeholder still counts as an active listing


# --- activity / days on market / price cuts ---


def test_activity_sums_ok_runs_only(conn):
    add_run(conn, "2026-07-08T06:00:00+00:00", n_new=2, n_delisted=1, n_drops=1)
    add_run(conn, "2026-07-09T06:00:00+00:00", n_new=1)
    add_run(conn, "2026-07-10T06:00:00+00:00", status="error", n_new=9)
    add_run(conn, "2026-07-01T06:00:00+00:00", n_new=9)  # before the window

    assert activity_since(conn, WATCH_ID, "2026-07-07") == (3, 1, 1)


def test_days_on_market_median(conn):
    add_listing(
        conn,
        "1",
        prices=[("2026-06-01", 100_000)],
        first_matched="2026-06-01",
        last_matched="2026-06-11",
        delisted_at="2026-07-01",
    )
    add_listing(
        conn,
        "2",
        prices=[("2026-06-01", 100_000)],
        first_matched="2026-06-01",
        last_matched="2026-06-21",
        delisted_at="2026-07-05",
    )
    add_listing(  # delisted before the window — excluded
        conn,
        "3",
        prices=[("2026-05-01", 100_000)],
        first_matched="2026-05-01",
        last_matched="2026-05-02",
        delisted_at="2026-05-04",
    )
    dom = days_on_market_stats(conn, WATCH_ID, since="2026-06-15")
    assert dom is not None
    assert dom.n == 2
    assert dom.median == pytest.approx(15.0)  # median of 10 and 20 days

    assert days_on_market_stats(conn, WATCH_ID, since="2026-08-01") is None


def test_price_cut_stats(conn):
    add_listing(  # one cut inside the window
        conn,
        "1",
        prices=[("2026-06-01", 100_000), ("2026-07-08", 90_000)],
        first_matched="2026-06-01",
        last_matched="2026-07-10",
    )
    add_listing(  # increase — not a cut
        conn,
        "2",
        prices=[("2026-06-01", 100_000), ("2026-07-08", 110_000)],
        first_matched="2026-06-01",
        last_matched="2026-07-10",
    )
    add_listing(  # cut before the window — excluded
        conn,
        "3",
        prices=[("2026-05-01", 100_000), ("2026-05-15", 80_000)],
        first_matched="2026-05-01",
        last_matched="2026-07-10",
    )
    cuts = price_cut_stats(conn, WATCH_ID, since="2026-07-01")
    assert cuts.n_active == 3
    assert cuts.n_cut == 1
    assert cuts.median_cut_pct == pytest.approx(-10.0)
    assert cuts.cut_share_pct == pytest.approx(100 / 3)


def test_price_cut_ignores_delisted(conn):
    add_listing(
        conn,
        "1",
        prices=[("2026-07-01", 100_000), ("2026-07-08", 90_000)],
        first_matched="2026-07-01",
        last_matched="2026-07-08",
        delisted_at="2026-07-10",
    )
    cuts = price_cut_stats(conn, WATCH_ID, since="2026-07-01")
    assert cuts.n_active == 0
    assert cuts.n_cut == 0


# --- rolling series & full trend ---


def test_rolling_median_series(conn):
    add_listing(
        conn,
        "1",
        area=50,
        prices=[("2026-07-01", 100_000), ("2026-07-08", 90_000)],
        first_matched="2026-07-01",
        last_matched="2026-07-10",
    )
    add_run(conn, "2026-07-01T06:00:00+00:00")
    add_run(conn, "2026-07-08T06:00:00+00:00")

    series = rolling_median_pm2(conn, WATCH_ID, on_date="2026-07-10", days=30)
    assert series == [
        ("2026-07-01", pytest.approx(2000.0)),
        ("2026-07-08", pytest.approx(1800.0)),
        ("2026-07-10", pytest.approx(1800.0)),  # on_date included even without an ok run
    ]


def test_compute_trend_deltas(conn):
    # Two listings from day 1; one cut 90k -> 81k within the week; one new on day 8.
    add_listing(
        conn,
        "1",
        area=50,
        prices=[("2026-07-01", 100_000)],
        first_matched="2026-07-01",
        last_matched="2026-07-10",
    )
    add_listing(
        conn,
        "2",
        area=50,
        prices=[("2026-07-01", 90_000), ("2026-07-09", 81_000)],
        first_matched="2026-07-01",
        last_matched="2026-07-10",
    )
    add_listing(
        conn,
        "3",
        area=50,
        prices=[("2026-07-08", 120_000)],
        first_matched="2026-07-08",
        last_matched="2026-07-10",
    )
    add_run(conn, "2026-07-08T06:00:00+00:00", n_new=1, n_drops=1)

    trend = compute_trend(conn, WATCH_ID, on_date="2026-07-10", period_days=7)

    # 2026-07-03: pm2s = [2000, 1800] -> median 1900. Now: [2000, 1620, 2400] -> 2000.
    assert trend.median_pm2_prev == pytest.approx(1900.0)
    assert trend.median_pm2_now == pytest.approx(2000.0)
    assert trend.pm2_delta_pct == pytest.approx(100 / 19, rel=1e-3)
    assert (trend.active_now, trend.active_prev, trend.active_delta) == (3, 2, 1)
    assert (trend.n_new, trend.n_drops, trend.n_delisted) == (1, 1, 0)
    assert trend.cuts is not None and trend.cuts.n_cut == 1


def test_compute_trend_on_young_watch_has_no_comparison(conn):
    add_listing(
        conn,
        "1",
        prices=[("2026-07-09", 100_000)],
        first_matched="2026-07-09",
        last_matched="2026-07-10",
    )
    trend = compute_trend(conn, WATCH_ID, on_date="2026-07-10", period_days=7)
    assert trend.median_pm2_prev is None
    assert trend.active_prev is None
    assert trend.pm2_delta_pct is None
    assert trend.active_delta is None
    assert trend.has_comparison is False
