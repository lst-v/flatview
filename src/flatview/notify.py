"""Push notifications via ntfy (https://ntfy.sh or self-hosted).

Publishing uses the JSON endpoint (POST to the server root) rather than
per-topic PUT so that titles and messages with diacritics survive — HTTP
headers are latin-1 only.
"""

from __future__ import annotations

import logging

import requests

from flatview.config import NtfyConfig
from flatview.errors import NotifyError
from flatview.html_report import _fmt
from flatview.track import WatchEvents

logger = logging.getLogger(__name__)

_MAX_LINES = 12


def build_push_message(events: list[WatchEvents], *, max_lines: int = _MAX_LINES) -> str:
    """Short phone-sized summary: one line per event, URLs tappable in ntfy."""
    lines: list[str] = []
    for ev in events:
        if ev.error:
            lines.append(f"{ev.watch.name}: FAILED — {ev.error}")
            continue
        if not (ev.new or ev.price_drops or ev.delisted):
            continue
        parts = []
        if ev.new:
            parts.append(f"{len(ev.new)} new")
        if ev.price_drops:
            parts.append(f"{len(ev.price_drops)} drops")
        if ev.delisted:
            parts.append(f"{len(ev.delisted)} delisted")
        lines.append(f"{ev.watch.name}: {', '.join(parts)}")
        for l in ev.new:
            area = f" · {l.area:.0f} m²" if l.area else ""
            lines.append(f"NEW {_fmt(l.price)} {l.currency}{area} — {l.title} {l.url}")
        for c in ev.price_drops:
            lines.append(
                f"DROP {c.pct:+.1f}% → {_fmt(c.new_price)} {c.listing.currency} — "
                f"{c.listing.title} {c.listing.url}"
            )
        for d in ev.delisted:
            lines.append(f"GONE {d.title} (last {_fmt(d.last_price)})")

    if len(lines) > max_lines:
        extra = len(lines) - max_lines
        lines = lines[:max_lines] + [f"… and {extra} more — see the digest"]
    return "\n".join(lines)


def send_ntfy(cfg: NtfyConfig, *, title: str, message: str) -> None:
    """Publish one notification; raises NotifyError on failure."""
    payload = {"topic": cfg.topic, "title": title, "message": message, "tags": ["house"]}
    headers = {}
    if cfg.token:
        headers["Authorization"] = f"Bearer {cfg.token}"
    try:
        resp = requests.post(cfg.server, json=payload, headers=headers, timeout=30)
    except requests.RequestException as e:
        raise NotifyError(f"ntfy push failed: {e}") from e
    if resp.status_code >= 400:
        raise NotifyError(f"ntfy push failed: HTTP {resp.status_code} — {resp.text[:200]}")
    logger.info("ntfy push sent to %s/%s", cfg.server, cfg.topic)
