"""Tracking pipeline: run saved watches, detect events, record run history.

Events per watch: NEW listings (first time matched by this watch), price
drops/increases (vs last stored price), delistings (not seen for a grace
window), and two-sided outliers (bargain/overpriced).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from flatview.analytics import (
    annotate_segments,
    compute_stats,
    flag_outliers_iqr,
    iqr_fence,
)
from flatview.client import BazosClient
from flatview.dedup import dedupe, find_duplicate_groups
from flatview.models import Listing
from flatview.scrape import scrape
from flatview.storage import (
    backfill_history,
    backup_db,
    default_db_path,
    find_delistable,
    get_prior_prices,
    last_successful_run,
    listing_key,
    mark_delisted,
    open_db,
    record_run_finish,
    record_run_start,
    unseen_watch_keys,
    upsert_listings,
    upsert_watch_listings,
)
from flatview.trends import (
    PriceStory,
    TrendSummary,
    build_price_stories,
    compute_trend,
    top_deals,
)
from flatview.watches import Watch, get_watch, list_watches

logger = logging.getLogger(__name__)


@dataclass
class PriceChange:
    listing: Listing
    old_price: float
    new_price: float

    @property
    def pct(self) -> float:
        return (self.new_price - self.old_price) / self.old_price * 100


@dataclass
class DelistedInfo:
    source: str
    listing_key: str
    title: str
    url: str
    last_price: float | None
    first_matched: str
    last_matched: str

    @property
    def days_on_market(self) -> int:
        first = date.fromisoformat(self.first_matched)
        last = date.fromisoformat(self.last_matched)
        return (last - first).days


@dataclass
class WatchEvents:
    watch: Watch
    is_baseline: bool = False
    new: list[Listing] = field(default_factory=list)
    price_drops: list[PriceChange] = field(default_factory=list)
    price_increases: list[PriceChange] = field(default_factory=list)
    delisted: list[DelistedInfo] = field(default_factory=list)
    bargains: list[Listing] = field(default_factory=list)
    overpriced: list[Listing] = field(default_factory=list)
    top_deals: list[tuple[Listing, float]] = field(default_factory=list)  # (listing, score)
    stories: dict[tuple[str, str], PriceStory] = field(default_factory=dict)
    fence: tuple[float, float] | None = None  # (low, high) €/m² IQR fence
    stats: dict = field(default_factory=dict)
    trend: TrendSummary | None = None  # deltas vs previous period, DOM, price cuts
    n_listings: int = 0
    n_unique: int = 0  # after cross-source dedup; stats/outliers are computed on these
    error: str | None = None


def _suppress_duplicate_new(
    new: list[Listing],
    dup_groups: list[list[Listing]],
    watch_name: str,
) -> list[Listing]:
    """Drop NEW alerts that are cross-posts of the same flat.

    A listing new to one portal but duplicating an already-tracked listing
    (its group has a non-new member) is a cross-post, not a new flat. When a
    flat debuts on several portals in the same run, alert once (canonical).
    """
    if not new:
        return new
    partners: dict[int, list[Listing]] = {}
    for group in dup_groups:
        for l in group:
            partners[id(l)] = [x for x in group if x is not l]

    new_ids = {id(l) for l in new}
    kept: list[Listing] = []
    kept_ids: set[int] = set()
    suppressed = 0
    for l in new:
        group_mates = partners.get(id(l), [])
        if any(id(p) not in new_ids for p in group_mates):
            suppressed += 1  # cross-post of a flat we already track
        elif any(id(p) in kept_ids for p in group_mates):
            suppressed += 1  # same flat already alerted in this run
        else:
            kept.append(l)
            kept_ids.add(id(l))
    if suppressed:
        logger.info(
            "watch '%s': suppressed %d duplicate NEW alert(s) (cross-posted flats)",
            watch_name,
            suppressed,
        )
    return kept


def run_watch(
    conn: sqlite3.Connection,
    client: BazosClient,
    watch: Watch,
    *,
    observed_at: str | None = None,
    delist_after_days: int = 2,
    iqr_k: float = 1.5,
    dry_run: bool = False,
) -> WatchEvents:
    """Scrape one watch and detect events. Mutates the DB unless dry_run."""
    if watch.id is None:
        raise ValueError(f"watch '{watch.name}' has no id — not loaded from the DB?")
    observed_at = observed_at or date.today().isoformat()
    events = WatchEvents(watch=watch)

    run_id: int | None = None
    if not dry_run:
        run_id = record_run_start(
            conn, watch.id, started_at=datetime.now(UTC).isoformat(timespec="seconds")
        )

    try:
        results = scrape(watch.params, client)
    except Exception as e:
        logger.error("watch '%s': scrape failed: %s", watch.name, e)
        events.error = str(e)
        if run_id is not None:
            record_run_finish(conn, run_id, status="error", error=str(e))
        return events

    listings = [l for r in results for l in r.listings]
    events.n_listings = len(listings)

    # All portals failed and nothing came back — network down or blocked.
    fetch_errors = [r.error for r in results if r.error]
    if not listings and fetch_errors:
        msg = "; ".join(fetch_errors)
        logger.error("watch '%s': no listings, fetch errors: %s", watch.name, msg)
        events.error = msg
        if run_id is not None:
            record_run_finish(conn, run_id, status="error", error=msg)
        return events

    annotate_segments(listings)

    # Baseline = this watch has never completed a run; suppress the NEW flood.
    events.is_baseline = last_successful_run(conn, watch.id) is None

    # Price events vs last stored price — must read BEFORE upsert.
    prior = get_prior_prices(conn, listings)
    for l in listings:
        key = (l.source, listing_key(l))
        old = prior.get(key)
        if old is not None and l.price is not None and l.price != old:
            change = PriceChange(listing=l, old_price=old, new_price=l.price)
            if l.price < old:
                events.price_drops.append(change)
            else:
                events.price_increases.append(change)

    if dry_run:
        new_keys = unseen_watch_keys(conn, watch.id, listings)
    else:
        upsert_listings(conn, listings, observed_at=observed_at)
        new_keys = upsert_watch_listings(conn, watch.id, listings, observed_at)
    backfill_history(conn, listings)

    # Cross-source entity resolution: the same flat posted on several portals.
    dup_groups = find_duplicate_groups(listings)
    unique = dedupe(listings, dup_groups)
    events.n_unique = len(unique)

    if not events.is_baseline:
        by_key = {(l.source, listing_key(l)): l for l in listings}
        events.new = _suppress_duplicate_new(
            [by_key[k] for k in new_keys if k in by_key], dup_groups, watch.name
        )

    # Delist check: only after a successful, non-empty scrape — an empty or
    # failed run must never mass-delist (HTML drift / network protection).
    if listings:
        cutoff = (date.fromisoformat(observed_at) - timedelta(days=delist_after_days)).isoformat()
        rows = find_delistable(conn, watch.id, older_than=cutoff)
        if rows:
            events.delisted = [
                DelistedInfo(
                    source=r[0],
                    listing_key=r[1],
                    first_matched=r[2],
                    last_matched=r[3],
                    title=r[4],
                    url=r[5],
                    last_price=r[6],
                )
                for r in rows
            ]
            if not dry_run:
                mark_delisted(conn, watch.id, [(r[0], r[1]) for r in rows], at=observed_at)

    # Analytics run on the deduped pool so cross-posted flats count once.
    flag_outliers_iqr(unique, k=iqr_k)
    events.bargains = [l for l in unique if l.outlier_side == "bargain"]
    events.overpriced = [l for l in unique if l.outlier_side == "overpriced"]
    events.fence = iqr_fence(unique, k=iqr_k)
    events.stats = compute_stats(unique)

    # Price stories need today's prices in the DB, so real runs only (like
    # trends); deal ranking degrades to pure discount ranking without them.
    if not dry_run:
        events.stories = build_price_stories(conn, unique, on_date=observed_at)
    median_pm2 = (events.stats.get("pm2") or {}).get("p50")
    events.top_deals = top_deals(unique, events.stories, median_pm2)

    # Trends read the freshly upserted history, so they only exist for real
    # runs; a trend failure must not abort the run (run row would stay stuck).
    if not dry_run:
        try:
            events.trend = compute_trend(conn, watch.id, on_date=observed_at)
            # This run isn't recorded yet — fold its events into the activity window.
            events.trend.n_new += len(events.new)
            events.trend.n_delisted += len(events.delisted)
            events.trend.n_drops += len(events.price_drops)
        except Exception:
            logger.exception("watch '%s': trend computation failed", watch.name)

    if run_id is not None:
        record_run_finish(
            conn,
            run_id,
            status="ok" if listings else "empty",
            n_listings=len(listings),
            n_new=len(events.new),
            n_price_drops=len(events.price_drops),
            n_delisted=len(events.delisted),
        )
    return events


def run_track(
    *,
    db_path: Path | None = None,
    watch_name: str | None = None,
    dry_run: bool = False,
    delist_after_days: int = 2,
    iqr_k: float = 1.5,
    backup_keep: int = 7,
    client: BazosClient | None = None,
    observed_at: str | None = None,
) -> tuple[int, list[WatchEvents]]:
    """Run all active watches (or one by name). Returns (exit_code, events).

    Exit codes: 0 = all ok, 1 = at least one watch failed, 2 = usage error.
    """
    db_path = db_path or default_db_path()
    conn = open_db(db_path)

    # Snapshot the DB before this run mutates it (daily, rotated).
    if not dry_run:
        try:
            backup = backup_db(conn, db_path.parent / "backups", keep=backup_keep)
            if backup:
                logger.info("DB backed up to %s", backup)
        except (sqlite3.Error, OSError) as e:
            logger.warning("DB backup failed: %s", e)
    client = client or BazosClient()
    try:
        if watch_name:
            watch = get_watch(conn, watch_name)
            if watch is None:
                logger.error("no watch named '%s'", watch_name)
                return 2, []
            watches = [watch]
        else:
            watches = list_watches(conn)

        if not watches:
            logger.warning("no active watches — add one with `flatview watch add`")
            return 0, []

        all_events: list[WatchEvents] = []
        for watch in watches:
            logger.info("running watch '%s'…", watch.name)
            events = run_watch(
                conn,
                client,
                watch,
                observed_at=observed_at,
                delist_after_days=delist_after_days,
                iqr_k=iqr_k,
                dry_run=dry_run,
            )
            all_events.append(events)

        return (1 if any(e.error for e in all_events) else 0), all_events
    finally:
        conn.close()
