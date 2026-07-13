from __future__ import annotations

from flatview.client import BazosClient


class _FakeResponse:
    def __init__(self, text: str = "<html></html>") -> None:
        self.text = text
        self.encoding: str | None = None

    def raise_for_status(self) -> None:
        pass


def test_retry_adapter_mounted():
    client = BazosClient(retries=5)
    for scheme in ("https://example.com", "http://example.com"):
        retry = client._session.get_adapter(scheme).max_retries
        assert retry.total == 5
        assert 429 in retry.status_forcelist
        assert 503 in retry.status_forcelist
        assert retry.allowed_methods == frozenset({"GET"})


def test_timeout_plumbed_to_request(monkeypatch):
    client = BazosClient(timeout=7.5, delay=0)
    captured: dict = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _FakeResponse("ok")

    monkeypatch.setattr(client._session, "get", fake_get)
    text = client.get("https://example.com/page")

    assert text == "ok"
    assert captured["url"] == "https://example.com/page"
    assert captured["timeout"] == 7.5


def test_rate_limit_sleeps_between_requests(monkeypatch):
    client = BazosClient(delay=1.0)
    sleeps: list[float] = []

    monkeypatch.setattr(client._session, "get", lambda url, **kw: _FakeResponse())
    monkeypatch.setattr("flatview.client.time.sleep", lambda s: sleeps.append(s))

    clock = iter([100.0, 100.0, 100.2, 100.2])  # elapsed 0.2s between calls
    monkeypatch.setattr("flatview.client.time.monotonic", lambda: next(clock))

    client.get("https://example.com/1")
    client.get("https://example.com/2")

    assert len(sleeps) == 1
    assert abs(sleeps[0] - 0.8) < 1e-9


def test_no_sleep_when_delay_zero(monkeypatch):
    client = BazosClient(delay=0)
    sleeps: list[float] = []

    monkeypatch.setattr(client._session, "get", lambda url, **kw: _FakeResponse())
    monkeypatch.setattr("flatview.client.time.sleep", lambda s: sleeps.append(s))

    client.get("https://example.com/1")
    client.get("https://example.com/2")

    assert sleeps == []
