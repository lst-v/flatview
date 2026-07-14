"""Market trend metrics computed from stored tracking history.

price_history only records a row when a price changes, so "price as of D"
means the most recent observation on or before D. A listing counts as active
on D for a watch when its membership window covers D (first_matched ≤ D ≤
last_matched). Cross-posts are collapsed by (rounded price, rounded area) —
an approximation of the dedup rule that holds because genuine cross-posts
carry exactly synced prices.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta

from flatview.analytics import PLACEHOLDER_PRICE_MAX, compute_percentiles


@dataclass
class DaysOnMarketStats:
    n: int
    median: float


@dataclass
class PriceCutStats:
    n_active: int
    n_cut: int  # listings with at least one price cut in the window
    median_cut_pct: float | None  # negative, e.g. -3.2

    @property
    def cut_share_pct(self) -> float:
        return self.n_cut / self.n_active * 100 if self.n_active else 0.0


@dataclass
class TrendSummary:
    period_days: int
    window_days: int
    median_pm2_now: float | None = None
    median_pm2_prev: float | None = None
    active_now: int | None = None
    active_prev: int | None = None
    n_new: int = 0  # over the last period_days, from watch_runs
    n_delisted: int = 0
    n_drops: int = 0
    days_on_market: DaysOnMarketStats | None = None
    cuts: PriceCutStats | None = None
    series: list[tuple[str, float]] = field(default_factory=list)  # (date, median €/m²)

    @property
    def pm2_delta_pct(self) -> float | None:
        if self.median_pm2_now is None or not self.median_pm2_prev:
            return None
        return (self.median_pm2_now / self.median_pm2_prev - 1) * 100

    @property
    def active_delta(self) -> int | None:
        if self.active_now is None or self.active_prev is None:
            return None
        return self.active_now - self.active_prev

    @property
    def has_comparison(self) -> bool:
        return self.pm2_delta_pct is not None or self.active_delta is not None


def _entity_key(source: str, listing_key: str, price: float | None, area: float | None) -> tuple:
    """Cross-post dedup key: exact synced price + rounded area; else keep distinct."""
    if price is not None and price > PLACEHOLDER_PRICE_MAX and area:
        return (round(price), round(area))
    return (source, listing_key)


def snapshot(conn: sqlite3.Connection, watch_id: int, on_date: str) -> tuple[float | None, int]:
    """(median €/m², active count) for the watch as of a date, cross-posts collapsed."""
    rows = conn.execute(
        """SELECT wl.source, wl.listing_key, l.area,
                  (SELECT ph.price FROM price_history ph
                    WHERE ph.source = wl.source AND ph.listing_key = wl.listing_key
                      AND ph.observed_at <= ?
                    ORDER BY ph.observed_at DESC LIMIT 1)
           FROM watch_listings wl
           LEFT JOIN listings l ON l.source = wl.source AND l.listing_key = wl.listing_key
           WHERE wl.watch_id = ? AND wl.first_matched <= ? AND wl.last_matched >= ?""",
        (on_date, watch_id, on_date, on_date),
    ).fetchall()

    entities: dict[tuple, tuple[float | None, float | None]] = {}
    for source, key, area, price in rows:
        entities.setdefault(_entity_key(source, key, price, area), (price, area))

    pm2s = [
        price / area
        for price, area in entities.values()
        if price is not None and price > PLACEHOLDER_PRICE_MAX and area and area > 0
    ]
    median = compute_percentiles(pm2s, (50,))[50] if pm2s else None
    return median, len(entities)


def activity_since(conn: sqlite3.Connection, watch_id: int, since: str) -> tuple[int, int, int]:
    """(n_new, n_delisted, n_price_drops) summed over successful runs since a date."""
    row = conn.execute(
        """SELECT COALESCE(SUM(n_new), 0), COALESCE(SUM(n_delisted), 0),
                  COALESCE(SUM(n_price_drops), 0)
           FROM watch_runs
           WHERE watch_id = ? AND status = 'ok' AND started_at >= ?""",
        (watch_id, since),
    ).fetchone()
    return int(row[0]), int(row[1]), int(row[2])


def days_on_market_stats(
    conn: sqlite3.Connection, watch_id: int, *, since: str
) -> DaysOnMarketStats | None:
    """Median days on market for listings delisted since a date."""
    rows = conn.execute(
        """SELECT first_matched, last_matched FROM watch_listings
           WHERE watch_id = ? AND delisted_at IS NOT NULL AND delisted_at >= ?""",
        (watch_id, since),
    ).fetchall()
    days = [(date.fromisoformat(last) - date.fromisoformat(first)).days for first, last in rows]
    if not days:
        return None
    values = [float(d) for d in days]
    return DaysOnMarketStats(n=len(days), median=compute_percentiles(values, (50,))[50])


def price_cut_stats(conn: sqlite3.Connection, watch_id: int, *, since: str) -> PriceCutStats:
    """Price cuts among currently active watch listings since a date.

    Cross-posts appear in both the cut count and the active count, so the
    share stays roughly unbiased.
    """
    n_active = conn.execute(
        "SELECT COUNT(*) FROM watch_listings WHERE watch_id = ? AND delisted_at IS NULL",
        (watch_id,),
    ).fetchone()[0]

    rows = conn.execute(
        """SELECT wl.source, wl.listing_key, ph.observed_at, ph.price
           FROM watch_listings wl
           JOIN price_history ph
             ON ph.source = wl.source AND ph.listing_key = wl.listing_key
           WHERE wl.watch_id = ? AND wl.delisted_at IS NULL
           ORDER BY wl.source, wl.listing_key, ph.observed_at""",
        (watch_id,),
    ).fetchall()

    cut_listings: set[tuple[str, str]] = set()
    cut_pcts: list[float] = []
    prev_key: tuple[str, str] | None = None
    prev_price: float | None = None
    for source, key, observed_at, price in rows:
        k = (source, key)
        if k == prev_key and (
            prev_price is not None
            and price is not None
            and prev_price > PLACEHOLDER_PRICE_MAX
            and price < prev_price
            and observed_at >= since
        ):
            cut_listings.add(k)
            cut_pcts.append((price - prev_price) / prev_price * 100)
        prev_key, prev_price = k, price

    median_cut = compute_percentiles(cut_pcts, (50,))[50] if cut_pcts else None
    return PriceCutStats(n_active=n_active, n_cut=len(cut_listings), median_cut_pct=median_cut)


def rolling_median_pm2(
    conn: sqlite3.Connection, watch_id: int, *, on_date: str, days: int = 30
) -> list[tuple[str, float]]:
    """[(date, median €/m²)] per successful-run day in the window, ending at on_date."""
    cutoff = (date.fromisoformat(on_date) - timedelta(days=days)).isoformat()
    run_dates = {
        row[0]
        for row in conn.execute(
            """SELECT DISTINCT substr(started_at, 1, 10) FROM watch_runs
               WHERE watch_id = ? AND status = 'ok' AND substr(started_at, 1, 10) >= ?""",
            (watch_id, cutoff),
        )
    }
    run_dates.add(on_date)  # the current run isn't marked 'ok' yet when this executes

    out: list[tuple[str, float]] = []
    for d in sorted(dt for dt in run_dates if dt <= on_date):
        median, _ = snapshot(conn, watch_id, d)
        if median is not None:
            out.append((d, median))
    return out


def compute_trend(
    conn: sqlite3.Connection,
    watch_id: int,
    *,
    on_date: str,
    period_days: int = 7,
    window_days: int = 30,
) -> TrendSummary:
    """Assemble the per-watch trend summary: deltas vs period_days ago, plus
    days-on-market and price-cut stats over window_days."""
    prev_date = (date.fromisoformat(on_date) - timedelta(days=period_days)).isoformat()
    window_start = (date.fromisoformat(on_date) - timedelta(days=window_days)).isoformat()

    median_now, active_now = snapshot(conn, watch_id, on_date)
    median_prev, active_prev = snapshot(conn, watch_id, prev_date)
    n_new, n_delisted, n_drops = activity_since(conn, watch_id, prev_date)

    return TrendSummary(
        period_days=period_days,
        window_days=window_days,
        median_pm2_now=median_now,
        median_pm2_prev=median_prev,
        active_now=active_now or None,
        active_prev=active_prev or None,
        n_new=n_new,
        n_delisted=n_delisted,
        n_drops=n_drops,
        days_on_market=days_on_market_stats(conn, watch_id, since=window_start),
        cuts=price_cut_stats(conn, watch_id, since=window_start),
        series=rolling_median_pm2(conn, watch_id, on_date=on_date, days=window_days),
    )
