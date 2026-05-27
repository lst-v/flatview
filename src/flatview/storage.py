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
"""


def default_db_path() -> Path:
    """Return the default SQLite path under XDG data home."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "flatview" / "flatview.db"


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
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
                    l.source, key, l.url, l.title, l.city, l.postcode,
                    l.area, l.currency, l.segment, observed_at, observed_at, l.price,
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
                    l.url, l.title, l.city, l.postcode, l.area, l.currency,
                    l.segment, observed_at, l.price, l.source, key,
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


def median_pm2_over_time(
    conn: sqlite3.Connection, *, days: int = 180
) -> list[tuple[str, float]]:
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
        vals = sorted(by_date[d])
        m = vals[len(vals) // 2]
        out.append((d, m))
    return out
