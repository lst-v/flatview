"""SQLite persistence for flatview listings and price history.

Listings are keyed by (source, listing_key) where listing_key is a stable
identifier per source — bazos has a numeric id, others fall back to a sha1
of the canonical URL.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from flatview.analytics import compute_percentiles
from flatview.models import Listing

_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    source TEXT NOT NULL,
    listing_key TEXT NOT NULL,
    url TEXT,
    title TEXT,
    city TEXT,
    postcode TEXT,
    area REAL,
    currency TEXT,
    segment TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_price REAL,
    PRIMARY KEY (source, listing_key)
);
CREATE TABLE IF NOT EXISTS price_history (
    source TEXT NOT NULL,
    listing_key TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    price REAL,
    PRIMARY KEY (source, listing_key, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_listings_lastseen ON listings(last_seen);
CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    query TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'all',
    site TEXT NOT NULL DEFAULT 'bazos.sk',
    category TEXT NOT NULL DEFAULT 'reality',
    subcategory TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    radius INTEGER NOT NULL DEFAULT 25,
    strict_location INTEGER NOT NULL DEFAULT 0,
    zip TEXT NOT NULL DEFAULT '',
    price_from INTEGER,
    price_to INTEGER,
    title_filter TEXT NOT NULL DEFAULT '',
    pages INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watch_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    n_listings INTEGER,
    n_new INTEGER,
    n_price_drops INTEGER,
    n_delisted INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_watch_runs_watch ON watch_runs(watch_id, started_at);
CREATE TABLE IF NOT EXISTS watch_listings (
    watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    listing_key TEXT NOT NULL,
    first_matched TEXT NOT NULL,
    last_matched TEXT NOT NULL,
    delisted_at TEXT,
    PRIMARY KEY (watch_id, source, listing_key)
);
CREATE INDEX IF NOT EXISTS idx_watch_listings_lastmatched
    ON watch_listings(watch_id, last_matched);
"""


def default_db_path() -> Path:
    """Return the default SQLite path under XDG data home."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "flatview" / "flatview.db"


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def listing_key(listing: Listing) -> str:
    """Stable per-source key. Bazos uses the numeric id; others hash the URL."""
    if listing.id is not None:
        return str(listing.id)
    url = listing.url or listing.title or ""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def upsert_listings(
    conn: sqlite3.Connection,
    listings: list[Listing],
    observed_at: str | None = None,
) -> None:
    """Upsert listings; append a price_history row only when price changes."""
    observed_at = observed_at or date.today().isoformat()
    cur = conn.cursor()
    for l in listings:
        key = listing_key(l)
        cur.execute(
            "SELECT first_seen, last_price FROM listings WHERE source=? AND listing_key=?",
            (l.source, key),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                """INSERT INTO listings
                   (source, listing_key, url, title, city, postcode, area, currency,
                    segment, first_seen, last_seen, last_price)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    l.source,
                    key,
                    l.url,
                    l.title,
                    l.city,
                    l.postcode,
                    l.area,
                    l.currency,
                    l.segment,
                    observed_at,
                    observed_at,
                    l.price,
                ),
            )
            if l.price is not None:
                cur.execute(
                    "INSERT OR IGNORE INTO price_history VALUES (?,?,?,?)",
                    (l.source, key, observed_at, l.price),
                )
        else:
            first_seen, last_price = row
            cur.execute(
                """UPDATE listings
                   SET url=?, title=?, city=?, postcode=?, area=?, currency=?,
                       segment=?, last_seen=?, last_price=?
                   WHERE source=? AND listing_key=?""",
                (
                    l.url,
                    l.title,
                    l.city,
                    l.postcode,
                    l.area,
                    l.currency,
                    l.segment,
                    observed_at,
                    l.price,
                    l.source,
                    key,
                ),
            )
            if l.price is not None and l.price != last_price:
                cur.execute(
                    "INSERT OR IGNORE INTO price_history VALUES (?,?,?,?)",
                    (l.source, key, observed_at, l.price),
                )
    conn.commit()


def backfill_history(conn: sqlite3.Connection, listings: list[Listing]) -> None:
    """Populate first_seen and previous_price on each Listing from the DB."""
    cur = conn.cursor()
    for l in listings:
        key = listing_key(l)
        cur.execute(
            "SELECT first_seen FROM listings WHERE source=? AND listing_key=?",
            (l.source, key),
        )
        row = cur.fetchone()
        if row:
            l.first_seen = row[0]

        cur.execute(
            """SELECT price FROM price_history
               WHERE source=? AND listing_key=?
               ORDER BY observed_at DESC LIMIT 2""",
            (l.source, key),
        )
        rows = cur.fetchall()
        if len(rows) >= 2:
            l.previous_price = rows[1][0]


def query_recent_count(
    conn: sqlite3.Connection, *, segment: str | None = None, days: int = 30
) -> int:
    """Count listings observed in the last `days` days (optionally per segment)."""
    cutoff = (datetime.now(UTC).date() - timedelta(days=days)).isoformat()
    if segment:
        cur = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE last_seen >= ? AND segment = ?",
            (cutoff, segment),
        )
    else:
        cur = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE last_seen >= ?",
            (cutoff,),
        )
    return int(cur.fetchone()[0])


def median_pm2_over_time(conn: sqlite3.Connection, *, days: int = 180) -> list[tuple[str, float]]:
    """Return [(observed_at, median_pm2)] across recent observations.

    Joins price_history with listings.area; only listings with area > 0 contribute.
    """
    cutoff = (datetime.now(UTC).date() - timedelta(days=days)).isoformat()
    cur = conn.execute(
        """SELECT ph.observed_at, ph.price, l.area
           FROM price_history ph
           JOIN listings l ON l.source=ph.source AND l.listing_key=ph.listing_key
           WHERE ph.observed_at >= ? AND l.area > 0 AND ph.price IS NOT NULL""",
        (cutoff,),
    )
    by_date: dict[str, list[float]] = {}
    for observed_at, price, area in cur.fetchall():
        if area and area > 0:
            by_date.setdefault(observed_at, []).append(price / area)
    out: list[tuple[str, float]] = []
    for d in sorted(by_date):
        m = compute_percentiles(by_date[d], (50,))[50]
        out.append((d, m))
    return out


# --- Watch-run tracking (used by `flatview track`) ---


def record_run_start(conn: sqlite3.Connection, watch_id: int, started_at: str) -> int:
    cur = conn.execute(
        "INSERT INTO watch_runs (watch_id, started_at) VALUES (?, ?)",
        (watch_id, started_at),
    )
    conn.commit()
    assert cur.lastrowid is not None
    return cur.lastrowid


def record_run_finish(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: str,
    finished_at: str | None = None,
    n_listings: int = 0,
    n_new: int = 0,
    n_price_drops: int = 0,
    n_delisted: int = 0,
    error: str | None = None,
) -> None:
    finished_at = finished_at or datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute(
        """UPDATE watch_runs
           SET finished_at=?, status=?, n_listings=?, n_new=?,
               n_price_drops=?, n_delisted=?, error=?
           WHERE id=?""",
        (finished_at, status, n_listings, n_new, n_price_drops, n_delisted, error, run_id),
    )
    conn.commit()


def last_successful_run(conn: sqlite3.Connection, watch_id: int) -> str | None:
    """started_at of the most recent non-error, non-running run for this watch."""
    cur = conn.execute(
        """SELECT started_at FROM watch_runs
           WHERE watch_id=? AND status IN ('ok', 'empty')
           ORDER BY started_at DESC LIMIT 1""",
        (watch_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def get_prior_prices(
    conn: sqlite3.Connection, listings: list[Listing]
) -> dict[tuple[str, str], float | None]:
    """Last stored price per (source, key) — call BEFORE upsert_listings."""
    out: dict[tuple[str, str], float | None] = {}
    for l in listings:
        key = listing_key(l)
        cur = conn.execute(
            "SELECT last_price FROM listings WHERE source=? AND listing_key=?",
            (l.source, key),
        )
        row = cur.fetchone()
        if row is not None:
            out[(l.source, key)] = row[0]
    return out


def unseen_watch_keys(
    conn: sqlite3.Connection, watch_id: int, listings: list[Listing]
) -> set[tuple[str, str]]:
    """(source, key) pairs not yet in watch_listings for this watch."""
    unseen: set[tuple[str, str]] = set()
    for l in listings:
        key = listing_key(l)
        row = conn.execute(
            "SELECT 1 FROM watch_listings WHERE watch_id=? AND source=? AND listing_key=?",
            (watch_id, l.source, key),
        ).fetchone()
        if row is None:
            unseen.add((l.source, key))
    return unseen


def upsert_watch_listings(
    conn: sqlite3.Connection,
    watch_id: int,
    listings: list[Listing],
    observed_at: str,
) -> set[tuple[str, str]]:
    """Record per-watch membership; returns newly inserted (source, key) pairs.

    Reappearing listings get last_matched bumped and delisted_at cleared.
    """
    new_keys = unseen_watch_keys(conn, watch_id, listings)
    cur = conn.cursor()
    for l in listings:
        key = listing_key(l)
        if (l.source, key) in new_keys:
            cur.execute(
                """INSERT OR IGNORE INTO watch_listings
                   (watch_id, source, listing_key, first_matched, last_matched, delisted_at)
                   VALUES (?,?,?,?,?,NULL)""",
                (watch_id, l.source, key, observed_at, observed_at),
            )
        else:
            cur.execute(
                """UPDATE watch_listings SET last_matched=?, delisted_at=NULL
                   WHERE watch_id=? AND source=? AND listing_key=?""",
                (observed_at, watch_id, l.source, key),
            )
    conn.commit()
    return new_keys


def find_delistable(conn: sqlite3.Connection, watch_id: int, *, older_than: str) -> list[tuple]:
    """Active watch listings last matched before `older_than`.

    Rows: (source, listing_key, first_matched, last_matched, title, url, last_price).
    """
    cur = conn.execute(
        """SELECT wl.source, wl.listing_key, wl.first_matched, wl.last_matched,
                  COALESCE(l.title, ''), COALESCE(l.url, ''), l.last_price
           FROM watch_listings wl
           LEFT JOIN listings l ON l.source=wl.source AND l.listing_key=wl.listing_key
           WHERE wl.watch_id=? AND wl.delisted_at IS NULL AND wl.last_matched < ?""",
        (watch_id, older_than),
    )
    return cur.fetchall()


def mark_delisted(
    conn: sqlite3.Connection,
    watch_id: int,
    keys: list[tuple[str, str]],
    at: str,
) -> None:
    conn.executemany(
        """UPDATE watch_listings SET delisted_at=?
           WHERE watch_id=? AND source=? AND listing_key=?""",
        [(at, watch_id, source, key) for source, key in keys],
    )
    conn.commit()
