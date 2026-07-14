from __future__ import annotations

from flatview.storage import (
    backfill_history,
    backup_db,
    listing_key,
    open_db,
    query_recent_count,
    upsert_listings,
)


def test_backup_db_daily_and_rotation(tmp_path, make_listing):
    conn = open_db(tmp_path / "test.db")
    upsert_listings(conn, [make_listing(id=1)], observed_at="2026-07-01")
    backups = tmp_path / "backups"

    path = backup_db(conn, backups, keep=3, today="2026-07-01")
    assert path is not None and path.name == "flatview-2026-07-01.db"
    # Backup is a consistent, readable copy.
    copy = open_db(path)
    assert copy.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 1
    copy.close()

    # Same day: no second backup.
    assert backup_db(conn, backups, keep=3, today="2026-07-01") is None

    # Rotation keeps only the newest `keep`.
    for day in ("2026-07-02", "2026-07-03", "2026-07-04"):
        backup_db(conn, backups, keep=3, today=day)
    names = sorted(p.name for p in backups.glob("flatview-*.db"))
    assert names == [
        "flatview-2026-07-02.db",
        "flatview-2026-07-03.db",
        "flatview-2026-07-04.db",
    ]


def test_backup_db_disabled(tmp_path, make_listing):
    conn = open_db(tmp_path / "test.db")
    assert backup_db(conn, tmp_path / "backups", keep=0, today="2026-07-01") is None
    assert not (tmp_path / "backups").exists()


def test_listing_key_uses_id(make_listing):
    l = make_listing(id=42, source="bazos", url="https://example/inzerat/42/x.php")
    assert listing_key(l) == "42"


def test_listing_key_falls_back_to_url_hash(make_listing):
    l = make_listing(id=None, url="https://example.com/detail/abc/")
    key = listing_key(l)
    assert len(key) == 16
    assert key.isalnum()


def test_upsert_inserts_new_listing(tmp_path, make_listing):
    conn = open_db(tmp_path / "test.db")
    l = make_listing(id=1, price=100_000)
    upsert_listings(conn, [l], observed_at="2026-01-01")

    cur = conn.execute("SELECT first_seen, last_price FROM listings WHERE source=?", ("bazos",))
    row = cur.fetchone()
    assert row == ("2026-01-01", 100_000.0)

    cur = conn.execute("SELECT COUNT(*) FROM price_history")
    assert cur.fetchone()[0] == 1


def test_upsert_preserves_first_seen(tmp_path, make_listing):
    conn = open_db(tmp_path / "test.db")
    l = make_listing(id=1, price=100_000)
    upsert_listings(conn, [l], observed_at="2026-01-01")
    upsert_listings(conn, [l], observed_at="2026-02-01")

    cur = conn.execute("SELECT first_seen, last_seen FROM listings")
    row = cur.fetchone()
    assert row == ("2026-01-01", "2026-02-01")


def test_price_history_appended_only_on_change(tmp_path, make_listing):
    conn = open_db(tmp_path / "test.db")
    l = make_listing(id=1, price=100_000)
    upsert_listings(conn, [l], observed_at="2026-01-01")
    upsert_listings(conn, [l], observed_at="2026-02-01")  # same price
    cur = conn.execute("SELECT COUNT(*) FROM price_history")
    assert cur.fetchone()[0] == 1

    l.price = 90_000
    upsert_listings(conn, [l], observed_at="2026-03-01")
    cur = conn.execute("SELECT COUNT(*) FROM price_history")
    assert cur.fetchone()[0] == 2


def test_backfill_populates_listing_metadata(tmp_path, make_listing):
    conn = open_db(tmp_path / "test.db")
    l = make_listing(id=1, price=100_000)
    upsert_listings(conn, [l], observed_at="2026-01-01")
    l.price = 90_000
    upsert_listings(conn, [l], observed_at="2026-02-01")

    fresh = make_listing(id=1, price=90_000)
    backfill_history(conn, [fresh])
    assert fresh.first_seen == "2026-01-01"
    assert fresh.previous_price == 100_000.0


def test_query_recent_count(tmp_path, make_listing):
    from datetime import date

    conn = open_db(tmp_path / "test.db")
    today = date.today().isoformat()
    upsert_listings(conn, [make_listing(id=1, price=100_000)], observed_at=today)
    upsert_listings(conn, [make_listing(id=2, price=200_000)], observed_at="2000-01-01")

    assert query_recent_count(conn, days=30) == 1
