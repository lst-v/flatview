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

from flatview.analytics import PLACEHOLDER_PRICE_MAX, compute_percentiles, price_per_m2
from flatview.models import Listing
from flatview.storage import listing_key


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


@dataclass
class PriceStory:
    """One listing's pricing biography, reconstructed from stored history."""

    first_price: float | None = None
    n_cuts: int = 0
    total_pct: float | None = None  # current vs first observed price; negative = down
    days_tracked: int | None = None  # since flatview first saw it, not true market age

    @property
    def brief(self) -> str:
        """Short human summary, e.g. '2 cuts · −12% total · 47 d tracked'."""
        parts = []
        if self.n_cuts:
            parts.append(f"{self.n_cuts} cut{'s' if self.n_cuts != 1 else ''}")
            if self.total_pct:
                parts.append(f"{self.total_pct:+.0f}% total")
        if self.days_tracked is not None and self.days_tracked > 0:
            parts.append(f"{self.days_tracked} d tracked")
        return " · ".join(parts)


def build_price_stories(
    conn: sqlite3.Connection,
    listings: list[Listing],
    *,
    on_date: str,
) -> dict[tuple[str, str], PriceStory]:
    """Price story per (source, listing_key) from price_history up to on_date."""
    stories: dict[tuple[str, str], PriceStory] = {}
    for l in listings:
        key = listing_key(l)
        prices = [
            row[0]
            for row in conn.execute(
                """SELECT price FROM price_history
                   WHERE source = ? AND listing_key = ? AND observed_at <= ?
                     AND price IS NOT NULL
                   ORDER BY observed_at""",
                (l.source, key, on_date),
            )
        ]
        story = PriceStory()
        if prices:
            story.first_price = prices[0]
            pairs = zip(prices, prices[1:], strict=False)
            story.n_cuts = sum(1 for prev, cur in pairs if cur < prev)
            if prices[0] > PLACEHOLDER_PRICE_MAX and prices[-1] != prices[0]:
                story.total_pct = (prices[-1] / prices[0] - 1) * 100
        if l.first_seen:
            first = date.fromisoformat(l.first_seen)
            story.days_tracked = (date.fromisoformat(on_date) - first).days
        stories[(l.source, key)] = story
    return stories


def deal_score(
    listing: Listing,
    median_pm2: float | None,
    story: PriceStory | None,
) -> float | None:
    """How attractive a listing is vs its market. Transparent, in 'points':

    % below the median €/m², plus half the total price-cut % (a motivated
    seller), plus up to 5 points for time on market (capped at 60 days —
    stale listings are negotiable).
    """
    pm2 = price_per_m2(listing)
    if pm2 is None or not median_pm2:
        return None
    score = (median_pm2 - pm2) / median_pm2 * 100
    if story:
        if story.total_pct and story.total_pct < 0:
            score += -story.total_pct * 0.5
        if story.days_tracked:
            score += min(story.days_tracked, 60) / 60 * 5
    return score


def top_deals(
    listings: list[Listing],
    stories: dict[tuple[str, str], PriceStory],
    median_pm2: float | None,
    n: int = 5,
) -> list[tuple[Listing, float]]:
    """The n best-scoring listings, descending: [(listing, score)]."""
    scored = []
    for l in listings:
        score = deal_score(l, median_pm2, stories.get((l.source, listing_key(l))))
        if score is not None:
            scored.append((l, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:n]


def median_pm2_series_for_listings(
    conn: sqlite3.Connection,
    listings: list[Listing],
    *,
    on_date: str,
    days: int = 180,
) -> list[tuple[str, float]]:
    """As-of median €/m² series scoped to exactly the given listings.

    Replays each listing's price history: on date D it counts with its most
    recent price on or before D, and not at all before it first appeared.
    Only the passed entities enter the series, so a report chart stays
    scoped to its own query — a Košice search never bends a Michalovce
    chart. Note the pool is today's result set, so points far in the past
    omit flats that have since delisted (survivor bias).
    """
    cutoff = (date.fromisoformat(on_date) - timedelta(days=days)).isoformat()

    replays: list[tuple[Listing, list[tuple[str, float]]]] = []
    for l in listings:
        rows = conn.execute(
            """SELECT observed_at, price FROM price_history
               WHERE source = ? AND listing_key = ? AND price IS NOT NULL
               ORDER BY observed_at""",
            (l.source, listing_key(l)),
        ).fetchall()
        if rows:
            replays.append((l, rows))

    change_dates = {d for _, rows in replays for d, _ in rows}
    dates = sorted(d for d in change_dates | {on_date} if cutoff <= d <= on_date)

    series: list[tuple[str, float]] = []
    for day in dates:
        entities: dict[tuple, tuple[float, float | None]] = {}
        for l, rows in replays:
            past = [price for observed, price in rows if observed <= day]
            if not past:
                continue  # not yet on the market
            key = _entity_key(l.source, listing_key(l), past[-1], l.area)
            entities.setdefault(key, (past[-1], l.area))
        pm2s = [
            price / area
            for price, area in entities.values()
            if price > PLACEHOLDER_PRICE_MAX and area and area > 0
        ]
        if pm2s:
            series.append((day, compute_percentiles(pm2s, (50,))[50]))
    return series


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
