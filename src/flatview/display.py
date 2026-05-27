from __future__ import annotations

import difflib

from rich.console import Console
from rich.table import Table

from flatview.analytics import compute_stats, stats_by_segment
from flatview.models import Listing, SearchResult


_SEG_STYLE = {
    "new": "[green]NEW[/green]",
    "resale": "[blue]RESALE[/blue]",
    "unknown": "[dim]—[/dim]",
}


def _find_duplicates(results: list[SearchResult]) -> set[int]:
    """Find listings that appear on multiple sources via fuzzy title matching."""
    groups: dict[str, list[Listing]] = {}
    for r in results:
        for listing in r.listings:
            groups.setdefault(listing.source, []).append(listing)

    sources = list(groups.keys())
    if len(sources) < 2:
        return set()

    dup_ids: set[int] = set()
    for i, src_a in enumerate(sources):
        for src_b in sources[i + 1 :]:
            for la in groups[src_a]:
                for lb in groups[src_b]:
                    ratio = difflib.SequenceMatcher(
                        None, la.title.lower(), lb.title.lower()
                    ).ratio()
                    if ratio >= 0.7:
                        dup_ids.add(id(la))
                        dup_ids.add(id(lb))
    return dup_ids


def print_results(
    result: SearchResult,
    *,
    filter_pattern: str = "",
    duplicate_ids: set[int] | None = None,
    exclude_outliers: bool = False,
) -> None:
    """Print search results as a rich table with summary stats."""
    console = Console()

    if not result.listings:
        console.print("[yellow]No listings found.[/yellow]")
        return

    # Header
    header_parts = []
    if result.query:
        header_parts.append(f"[bold]{result.query}[/bold]")
    if result.category:
        header_parts.append(f"in [cyan]{result.category}[/cyan]")
    if result.location:
        header_parts.append(f"near [cyan]{result.location}[/cyan]")
    header_parts.append(f"on [cyan]{result.site}[/cyan]")
    if filter_pattern:
        header_parts.append(f"filter [magenta]/{filter_pattern}/[/magenta]")
    console.print(" ".join(header_parts))

    if result.total_count is not None:
        console.print(f"Total results: {result.total_count}")
    console.print(f"Showing: {len(result.listings)} listings\n")

    has_area = any(l.area is not None for l in result.listings)
    segments_present = {l.segment for l in result.listings}
    has_segments = len(segments_present - {"unknown"}) >= 1 and len(segments_present) > 1

    # Table
    table = Table(show_lines=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", max_width=50)
    if has_segments:
        table.add_column("Seg", width=8)
    table.add_column("Price", justify="right")
    if has_area:
        table.add_column("Area", justify="right", width=8)
        table.add_column("EUR/m²", justify="right", width=10)
    table.add_column("Location", max_width=25)
    table.add_column("Date", width=12)

    for i, listing in enumerate(result.listings, 1):
        price_str = (
            f"{listing.price:,.0f} {listing.currency}"
            if listing.price is not None
            else "[dim]N/A[/dim]"
        )
        location = listing.city
        if listing.postcode:
            location += f" ({listing.postcode})"

        prefix = ""
        if listing.is_outlier:
            prefix += "[red]*[/red] "
        if duplicate_ids and id(listing) in duplicate_ids:
            prefix += "[yellow]*[/yellow] "
        title_display = f"{prefix}{listing.title}"

        row = [str(i), title_display]
        if has_segments:
            row.append(_SEG_STYLE.get(listing.segment, listing.segment))
        row.append(price_str)
        if has_area:
            area_str = f"{listing.area:.0f} m²" if listing.area else "[dim]—[/dim]"
            pm2_str = (
                f"{listing.price / listing.area:,.0f}"
                if listing.price and listing.area
                else "[dim]—[/dim]"
            )
            row.extend([area_str, pm2_str])
        row.extend([location, listing.date])

        table.add_row(*row)

    console.print(table)
    _print_price_summary(console, result.listings, exclude_outliers=exclude_outliers)


def print_multi_results(
    results: list[SearchResult],
    *,
    filter_pattern: str = "",
    exclude_outliers: bool = False,
) -> None:
    """Print grouped results per source, then a combined summary."""
    console = Console()

    dup_ids = _find_duplicates(results)

    for result in results:
        if result.listings:
            console.print()
            print_results(
                result,
                filter_pattern=filter_pattern,
                duplicate_ids=dup_ids,
                exclude_outliers=exclude_outliers,
            )
            console.print()

    # Combined summary
    all_listings = [l for r in results for l in r.listings]
    if len(results) > 1 and all_listings:
        sources = [r.site for r in results if r.listings]
        dup_count = sum(1 for l in all_listings if id(l) in dup_ids)
        console.print(
            f"\n[bold]Combined summary[/bold] ({len(all_listings)} listings "
            f"from {', '.join(sources)})"
        )
        if dup_count:
            console.print(
                f"[yellow]Detected {dup_count} potential cross-source duplicates (marked with *)[/yellow]"
            )
        _print_price_summary(console, all_listings, exclude_outliers=exclude_outliers)


def _fmt_stat(v) -> str:
    return f"{v:,.0f}" if isinstance(v, (int, float)) else "—"


def _print_block(console: Console, label: str, stats: dict) -> None:
    price = stats.get("price") or {}
    pm2 = stats.get("pm2") or {}
    cur = stats.get("currency", "EUR")
    if not price.get("n") and not pm2.get("n"):
        return
    console.print(f"\n[bold]{label}[/bold]")
    if price.get("n"):
        console.print(
            f"  Price ({cur}, n={price['n']}): "
            f"P10 {_fmt_stat(price.get('p10'))}  "
            f"P25 {_fmt_stat(price.get('p25'))}  "
            f"P50 {_fmt_stat(price.get('p50'))}  "
            f"P75 {_fmt_stat(price.get('p75'))}  "
            f"P90 {_fmt_stat(price.get('p90'))}  "
            f"avg {_fmt_stat(price.get('avg'))}  "
            f"min {_fmt_stat(price.get('min'))}  "
            f"max {_fmt_stat(price.get('max'))}"
        )
    if pm2.get("n"):
        console.print(
            f"  {cur}/m² (n={pm2['n']}): "
            f"P10 {_fmt_stat(pm2.get('p10'))}  "
            f"P25 {_fmt_stat(pm2.get('p25'))}  "
            f"P50 {_fmt_stat(pm2.get('p50'))}  "
            f"P75 {_fmt_stat(pm2.get('p75'))}  "
            f"P90 {_fmt_stat(pm2.get('p90'))}  "
            f"avg {_fmt_stat(pm2.get('avg'))}  "
            f"min {_fmt_stat(pm2.get('min'))}  "
            f"max {_fmt_stat(pm2.get('max'))}"
        )


def _print_price_summary(
    console: Console, listings: list, *, exclude_outliers: bool = False
) -> None:
    if not listings:
        return
    n_outliers = sum(1 for l in listings if l.is_outlier)
    overall = compute_stats(listings, exclude_outliers=exclude_outliers)
    _print_block(console, "Stats", overall)
    if n_outliers:
        suffix = " (excluded from stats)" if exclude_outliers else " (still in stats)"
        console.print(
            f"[dim]Outliers: {n_outliers} flagged on EUR/m² IQR{suffix}.[/dim]"
        )
    per_seg = stats_by_segment(listings, exclude_outliers=exclude_outliers)
    label_map = {"new": "New build", "resale": "Resale", "unknown": "Unclassified"}
    if len(per_seg) >= 2:
        for seg in ("new", "resale", "unknown"):
            if seg in per_seg:
                _print_block(console, label_map[seg], per_seg[seg])
