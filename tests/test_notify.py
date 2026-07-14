from __future__ import annotations

import pytest
import requests

from flatview.config import NtfyConfig
from flatview.errors import NotifyError
from flatview.notify import build_push_message, send_ntfy
from flatview.track import PriceChange, WatchEvents
from flatview.watches import Watch


@pytest.fixture
def cfg():
    return NtfyConfig(topic="flatview-test")


class FakeResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


def test_send_ntfy_posts_json(cfg, monkeypatch):
    captured = {}

    def fake_post(url, *, json, headers, timeout):
        captured.update(url=url, json=json, headers=headers)
        return FakeResponse()

    monkeypatch.setattr("flatview.notify.requests.post", fake_post)
    send_ntfy(cfg, title="flatview: 2 new (mi-2izb)", message="Nový byt — 108,990 €")

    assert captured["url"] == "https://ntfy.sh"
    assert captured["json"]["topic"] == "flatview-test"
    assert captured["json"]["title"] == "flatview: 2 new (mi-2izb)"
    assert "Nový byt" in captured["json"]["message"]
    assert "Authorization" not in captured["headers"]


def test_send_ntfy_token_and_server(monkeypatch):
    cfg = NtfyConfig(topic="t", server="https://ntfy.example.com", token="tk_secret")
    captured = {}

    def fake_post(url, *, json, headers, timeout):
        captured.update(url=url, headers=headers)
        return FakeResponse()

    monkeypatch.setattr("flatview.notify.requests.post", fake_post)
    send_ntfy(cfg, title="t", message="m")

    assert captured["url"] == "https://ntfy.example.com"
    assert captured["headers"]["Authorization"] == "Bearer tk_secret"


def test_send_ntfy_raises_on_http_error(cfg, monkeypatch):
    monkeypatch.setattr(
        "flatview.notify.requests.post",
        lambda *a, **k: FakeResponse(status_code=403, text="forbidden"),
    )
    with pytest.raises(NotifyError, match="HTTP 403"):
        send_ntfy(cfg, title="t", message="m")


def test_send_ntfy_raises_on_network_error(cfg, monkeypatch):
    def fake_post(*a, **k):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr("flatview.notify.requests.post", fake_post)
    with pytest.raises(NotifyError, match="refused"):
        send_ntfy(cfg, title="t", message="m")


# --- healthcheck ping ---


def test_ping_healthcheck_ok_and_fail(monkeypatch):
    from flatview.notify import ping_healthcheck

    calls = []
    monkeypatch.setattr(
        "flatview.notify.requests.get",
        lambda url, timeout: calls.append(url) or FakeResponse(),
    )
    ping_healthcheck("https://hc-ping.com/abc", ok=True)
    ping_healthcheck("https://hc-ping.com/abc/", ok=False)
    assert calls == ["https://hc-ping.com/abc", "https://hc-ping.com/abc/fail"]


def test_ping_healthcheck_never_raises(monkeypatch):
    from flatview.notify import ping_healthcheck

    def fake_get(url, timeout):
        raise requests.ConnectionError("down")

    monkeypatch.setattr("flatview.notify.requests.get", fake_get)
    ping_healthcheck("https://hc-ping.com/abc", ok=True)  # must not raise


# --- message building ---


def test_build_push_message(make_listing):
    new = make_listing(id=1, title="Nový byt", price=108_990, area=59)
    dropped = make_listing(id=2, title="Zľava byt")
    ev = WatchEvents(watch=Watch(name="mi-2izb"), n_listings=10)
    ev.new = [new]
    ev.price_drops = [PriceChange(listing=dropped, old_price=100_000, new_price=90_000)]
    quiet = WatchEvents(watch=Watch(name="quiet"), n_listings=5)

    msg = build_push_message([ev, quiet])

    assert "mi-2izb: 1 new, 1 drops" in msg
    assert "NEW 108,990 EUR · 59 m² — Nový byt https://" in msg
    assert "DROP -10.0% → 90,000 EUR — Zľava byt" in msg
    assert "quiet" not in msg  # nothing happened there


def test_build_push_message_failed_watch():
    failed = WatchEvents(watch=Watch(name="down"), error="offline")
    assert build_push_message([failed]) == "down: FAILED — offline"


def test_build_push_message_truncates(make_listing):
    ev = WatchEvents(watch=Watch(name="w"), n_listings=30)
    ev.new = [make_listing(id=i, title=f"Byt {i}") for i in range(20)]

    msg = build_push_message([ev], max_lines=5)
    lines = msg.splitlines()
    assert len(lines) == 6
    assert lines[-1] == "… and 16 more — see the digest"
