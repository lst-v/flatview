"""Email-safe HTML digest for track runs.

Inline CSS only, no JS/Plotly — email clients strip scripts, so this is a
separate renderer from html_report (which stays browser-oriented).
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from flatview.analytics import price_per_m2
from flatview.html_report import _fmt
from flatview.models import Listing
from flatview.track import WatchEvents

_TABLE = "border-collapse:collapse;margin:8px 0 16px 0;font-size:14px"
_TH = "padding:4px 10px;border:1px solid #ddd;background:#f6f6f6;text-align:left"
_TD = "padding:4px 10px;border:1px solid #ddd"


def has_events(events: list[WatchEvents]) -> bool:
    """True when something notification-worthy happened (new/drops/delisted/errors)."""
    return any(e.new or e.price_drops or e.delisted or e.error for e in events)


def digest_subject(events: list[WatchEvents]) -> str:
    n_new = sum(len(e.new) for e in events)
    n_drops = sum(len(e.price_drops) for e in events)
    n_delisted = sum(len(e.delisted) for e in events)
    n_failed = sum(1 for e in events if e.error)

    parts = []
    if n_new:
        parts.append(f"{n_new} new")
    if n_drops:
        parts.append(f"{n_drops} drop{'s' if n_drops != 1 else ''}")
    if n_delisted:
        parts.append(f"{n_delisted} delisted")
    if n_failed:
        parts.append(f"{n_failed} failed")
    summary = ", ".join(parts) if parts else "no changes"
    names = ", ".join(e.watch.name for e in events)
    return f"flatview: {summary} ({names})"


def _listing_table(listings: list[Listing]) -> str:
    head = "".join(
        f"<th style='{_TH}'>{h}</th>" for h in ("Title", "Price", "m²", "€/m²", "City", "Segment")
    )
    rows = []
    for l in listings:
        title = f"<a href='{l.url}'>{l.title}</a>" if l.url else l.title
        seg = l.segment if l.segment != "unknown" else ""
        rows.append(
            f"<tr><td style='{_TD}'>{title}</td>"
            f"<td style='{_TD}'>{_fmt(l.price)}</td>"
            f"<td style='{_TD}'>{_fmt(l.area)}</td>"
            f"<td style='{_TD}'>{_fmt(price_per_m2(l))}</td>"
            f"<td style='{_TD}'>{l.city}</td>"
            f"<td style='{_TD}'>{seg}</td></tr>"
        )
    return (
        f"<table style='{_TABLE}'><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _stats_block(stats: dict) -> str:
    price = stats.get("price") or {}
    pm2 = stats.get("pm2") or {}
    if not price.get("n") and not pm2.get("n"):
        return ""
    currency = stats.get("currency", "EUR")
    head = "".join(
        f"<th style='{_TH}'>{h}</th>" for h in ("Metric", f"Price ({currency})", f"{currency}/m²")
    )
    rows = "".join(
        f"<tr><td style='{_TD}'>{label}</td>"
        f"<td style='{_TD}'>{_fmt(price.get(key))}</td>"
        f"<td style='{_TD}'>{_fmt(pm2.get(key))}</td></tr>"
        for label, key in (("P25", "p25"), ("Median", "p50"), ("P75", "p75"), ("Count", "n"))
    )
    return (
        f"<p style='margin:12px 0 0 0'><strong>Market snapshot</strong></p>"
        f"<table style='{_TABLE}'><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"
    )


def _watch_section(ev: WatchEvents) -> str:
    p = ev.watch.params
    meta = " · ".join(filter(None, [p.query, p.location, p.source]))
    parts = [f"<h2 style='margin:24px 0 4px 0'>{ev.watch.name}</h2>"]
    parts.append(f"<p style='color:#666;margin:0 0 8px 0'>{meta} — {ev.n_listings} listings</p>")

    if ev.error:
        parts.append(f"<p style='color:#c62828'><strong>Run failed:</strong> {ev.error}</p>")
        return "\n".join(parts)

    if ev.is_baseline:
        parts.append(
            "<p style='color:#666'>Baseline run — listings recorded; "
            "new-listing alerts start with the next run.</p>"
        )

    if ev.new:
        parts.append(
            f"<p><strong style='color:#0a7f33'>🆕 New listings ({len(ev.new)})</strong></p>"
        )
        parts.append(_listing_table(ev.new))

    if ev.price_drops:
        head = "".join(f"<th style='{_TH}'>{h}</th>" for h in ("Title", "Old", "New", "Δ%", "City"))
        rows = "".join(
            f"<tr><td style='{_TD}'><a href='{c.listing.url}'>{c.listing.title}</a></td>"
            f"<td style='{_TD}'>{_fmt(c.old_price)}</td>"
            f"<td style='{_TD}'><strong>{_fmt(c.new_price)}</strong></td>"
            f"<td style='{_TD};color:#0a7f33'>{c.pct:+.1f}%</td>"
            f"<td style='{_TD}'>{c.listing.city}</td></tr>"
            for c in ev.price_drops
        )
        parts.append(
            f"<p><strong style='color:#0a7f33'>📉 Price drops ({len(ev.price_drops)})</strong></p>"
        )
        parts.append(
            f"<table style='{_TABLE}'><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"
        )

    if ev.delisted:
        head = "".join(
            f"<th style='{_TH}'>{h}</th>" for h in ("Title", "Last price", "Days on market")
        )
        rows = "".join(
            f"<tr><td style='{_TD}'><a href='{d.url}'>{d.title}</a></td>"
            f"<td style='{_TD}'>{_fmt(d.last_price)}</td>"
            f"<td style='{_TD}'>{d.days_on_market}</td></tr>"
            for d in ev.delisted
        )
        parts.append(f"<p><strong>🚫 Delisted ({len(ev.delisted)})</strong></p>")
        parts.append(
            f"<table style='{_TABLE}'><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"
        )

    fence_note = ""
    if ev.fence:
        fence_note = (
            f"<p style='color:#666;font-size:13px'>IQR fence on €/m²: "
            f"{ev.fence[0]:,.0f} – {ev.fence[1]:,.0f}</p>"
        )
    if ev.bargains:
        parts.append(
            f"<p><strong style='color:#0a7f33'>"
            f"💰 Potential bargains ({len(ev.bargains)})</strong></p>"
        )
        parts.append(fence_note)
        parts.append(_listing_table(ev.bargains))
    if ev.overpriced:
        parts.append(
            f"<p><strong style='color:#c62828'>💸 Overpriced ({len(ev.overpriced)})</strong></p>"
        )
        if not ev.bargains:
            parts.append(fence_note)
        parts.append(_listing_table(ev.overpriced))

    parts.append(_stats_block(ev.stats))
    return "\n".join(parts)


def render_digest(events: list[WatchEvents], *, generated_at: datetime) -> str:
    body = "\n".join(_watch_section(ev) for ev in events)
    stamp = generated_at.strftime("%Y-%m-%d %H:%M")
    return (
        "<div style=\"font-family:-apple-system,'Segoe UI',Roboto,sans-serif;"
        'color:#222;max-width:800px">'
        f"<h1 style='margin-bottom:4px'>flatview digest</h1>"
        f"<p style='color:#666;margin:0 0 16px 0'>{stamp} · {len(events)} watch(es)</p>"
        f"{body}"
        "<p style='color:#999;font-size:12px;margin-top:24px'>Generated by flatview track.</p>"
        "</div>"
    )


def render_digest_text(events: list[WatchEvents]) -> str:
    lines = ["flatview digest", ""]
    for ev in events:
        if ev.error:
            lines.append(f"{ev.watch.name}: FAILED — {ev.error}")
            continue
        lines.append(
            f"{ev.watch.name}: {ev.n_listings} listings, {len(ev.new)} new, "
            f"{len(ev.price_drops)} price drops, {len(ev.delisted)} delisted, "
            f"{len(ev.bargains)} bargains, {len(ev.overpriced)} overpriced"
        )
        for l in ev.new:
            lines.append(f"  NEW: {l.title} — {_fmt(l.price)} {l.currency} — {l.url}")
        for c in ev.price_drops:
            lines.append(
                f"  DROP: {c.listing.title} — {_fmt(c.old_price)} -> {_fmt(c.new_price)} "
                f"({c.pct:+.1f}%) — {c.listing.url}"
            )
        for d in ev.delisted:
            lines.append(f"  DELISTED: {d.title} — last {_fmt(d.last_price)} — {d.url}")
    return "\n".join(lines)


def write_digest(html: str, digest_dir: Path, generated_at: datetime) -> Path:
    """Write a timestamped digest file and refresh latest.html; returns the file path."""
    digest_dir.mkdir(parents=True, exist_ok=True)
    name = f"digest_{generated_at.strftime('%Y-%m-%d_%H%M')}.html"
    path = digest_dir / name
    full = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>flatview digest</title></head><body>{html}</body></html>"
    )
    path.write_text(full, encoding="utf-8")
    shutil.copyfile(path, digest_dir / "latest.html")
    return path
