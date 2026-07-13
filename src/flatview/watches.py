"""Saved searches ("watches") persisted in the flatview SQLite DB.

A Watch is a name plus the SearchParams to re-run on every `flatview track`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime

from flatview.errors import FlatviewError
from flatview.scrape import SearchParams


@dataclass
class Watch:
    name: str
    params: SearchParams = field(default_factory=SearchParams)
    id: int | None = None
    active: bool = True
    created_at: str = ""


_COLUMNS = (
    "id, name, query, source, site, category, subcategory, location, radius, "
    "strict_location, zip, price_from, price_to, title_filter, pages, active, created_at"
)


def _row_to_watch(row: tuple) -> Watch:
    (
        watch_id,
        name,
        query,
        source,
        site,
        category,
        subcategory,
        location,
        radius,
        strict_location,
        zip_code,
        price_from,
        price_to,
        title_filter,
        pages,
        active,
        created_at,
    ) = row
    return Watch(
        name=name,
        params=SearchParams(
            query=query,
            source=source,
            site=site,
            category=category,
            subcategory=subcategory,
            location=location,
            radius=radius,
            strict_location=bool(strict_location),
            zip_code=zip_code,
            price_from=price_from,
            price_to=price_to,
            title_filter=title_filter,
            pages=pages,
        ),
        id=watch_id,
        active=bool(active),
        created_at=created_at,
    )


def add_watch(conn: sqlite3.Connection, watch: Watch) -> int:
    """Insert a watch; raises FlatviewError when the name is already taken."""
    p = watch.params
    created = watch.created_at or datetime.now(UTC).isoformat(timespec="seconds")
    # Tracking wants full coverage: default (None) becomes 0 = all pages.
    pages = p.pages if p.pages is not None else 0
    try:
        cur = conn.execute(
            """INSERT INTO watches
               (name, query, source, site, category, subcategory, location, radius,
                strict_location, zip, price_from, price_to, title_filter, pages,
                active, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                watch.name,
                p.query,
                p.source,
                p.site,
                p.category,
                p.subcategory,
                p.location,
                p.radius,
                int(p.strict_location),
                p.zip_code,
                p.price_from,
                p.price_to,
                p.title_filter,
                pages,
                int(watch.active),
                created,
            ),
        )
    except sqlite3.IntegrityError as e:
        raise FlatviewError(f"watch '{watch.name}' already exists") from e
    conn.commit()
    assert cur.lastrowid is not None
    watch.id = cur.lastrowid
    watch.created_at = created
    return watch.id


def get_watch(conn: sqlite3.Connection, name: str) -> Watch | None:
    cur = conn.execute(f"SELECT {_COLUMNS} FROM watches WHERE name = ?", (name,))
    row = cur.fetchone()
    return _row_to_watch(row) if row else None


def list_watches(conn: sqlite3.Connection, *, include_inactive: bool = False) -> list[Watch]:
    sql = f"SELECT {_COLUMNS} FROM watches"
    if not include_inactive:
        sql += " WHERE active = 1"
    sql += " ORDER BY name"
    return [_row_to_watch(row) for row in conn.execute(sql).fetchall()]


def remove_watch(conn: sqlite3.Connection, name: str) -> bool:
    """Delete a watch by name. FK cascades clean up per-watch tracking rows."""
    cur = conn.execute("DELETE FROM watches WHERE name = ?", (name,))
    conn.commit()
    return cur.rowcount > 0
