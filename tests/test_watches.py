from __future__ import annotations

import pytest

from flatview.errors import FlatviewError
from flatview.scrape import SearchParams
from flatview.storage import open_db
from flatview.watches import Watch, add_watch, get_watch, list_watches, remove_watch


@pytest.fixture
def conn(tmp_path):
    conn = open_db(tmp_path / "test.db")
    yield conn
    conn.close()


FULL_PARAMS = SearchParams(
    query="2 izbový byt",
    source="all",
    site="bazos.cz",
    category="reality",
    subcategory="predam/byt",
    location="Michalovce",
    radius=10,
    strict_location=True,
    zip_code="07101",
    price_from=50_000,
    price_to=150_000,
    title_filter="rekonštr",
    pages=3,
)


def test_add_and_get_roundtrip_all_fields(conn):
    watch_id = add_watch(conn, Watch(name="mi-2izb", params=FULL_PARAMS))
    assert watch_id > 0

    loaded = get_watch(conn, "mi-2izb")
    assert loaded is not None
    assert loaded.id == watch_id
    assert loaded.active is True
    assert loaded.created_at  # populated
    assert loaded.params == FULL_PARAMS


def test_default_pages_stored_as_all(conn):
    add_watch(conn, Watch(name="w", params=SearchParams(query="byt")))  # pages=None
    loaded = get_watch(conn, "w")
    assert loaded is not None
    assert loaded.params.pages == 0  # tracking wants full coverage


def test_duplicate_name_raises(conn):
    add_watch(conn, Watch(name="dup"))
    with pytest.raises(FlatviewError, match="already exists"):
        add_watch(conn, Watch(name="dup"))


def test_get_missing_returns_none(conn):
    assert get_watch(conn, "nope") is None


def test_remove(conn):
    add_watch(conn, Watch(name="gone"))
    assert remove_watch(conn, "gone") is True
    assert get_watch(conn, "gone") is None
    assert remove_watch(conn, "gone") is False


def test_list_filters_inactive(conn):
    add_watch(conn, Watch(name="on"))
    add_watch(conn, Watch(name="off", active=False))

    assert [w.name for w in list_watches(conn)] == ["on"]
    assert [w.name for w in list_watches(conn, include_inactive=True)] == ["off", "on"]
