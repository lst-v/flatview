from __future__ import annotations

from rich.console import Console
from rich.table import Table

from b_scrape.models import SearchResult


def print_results(result: SearchResult, *, filter_pattern: str = "") -> None:
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

    # Table
    table = Table(show_lines=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", max_width=50)
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

        row = [str(i), listing.title, price_str]
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
    _print_price_summary(console, result.listings)


def print_multi_results(
    results: list[SearchResult], *, filter_pattern: str = ""
) -> None:
    """Print grouped results per source, then a combined summary."""
    console = Console()

    for result in results:
        if result.listings:
            console.print()
            print_results(result, filter_pattern=filter_pattern)
            console.print()

    # Combined summary
    all_listings = [l for r in results for l in r.listings]
    if len(results) > 1 and all_listings:
        sources = [r.site for r in results if r.listings]
        console.print(
            f"\n[bold]Combined summary[/bold] ({len(all_listings)} listings "
            f"from {', '.join(sources)})"
        )
        _print_price_summary(console, all_listings)


def _print_price_summary(console: Console, listings: list) -> None:
    """Print price and price/m² stats."""
    prices = [l.price for l in listings if l.price is not None]
    if not prices:
        return

    currency = next(
        (l.currency for l in listings if l.price is not None), "EUR"
    )
    avg = sum(prices) / len(prices)
    prices_sorted = sorted(prices)
    median = prices_sorted[len(prices_sorted) // 2]

    console.print(f"\n[bold]Price summary[/bold] ({len(prices)} with price):")
    console.print(f"  Average: {avg:,.0f} {currency}")
    console.print(f"  Min:     {min(prices):,.0f} {currency}")
    console.print(f"  Max:     {max(prices):,.0f} {currency}")
    console.print(f"  Median:  {median:,.0f} {currency}")

    # Price per m² stats if area data is available
    pm2 = [
        l.price / l.area
        for l in listings
        if l.price is not None and l.area is not None and l.area > 0
    ]
    if pm2:
        pm2_sorted = sorted(pm2)
        pm2_median = pm2_sorted[len(pm2_sorted) // 2]
        console.print(
            f"\n[bold]Price/m² summary[/bold] ({len(pm2)} with area):"
        )
        console.print(f"  Average: {sum(pm2) / len(pm2):,.0f} {currency}/m²")
        console.print(f"  Min:     {min(pm2):,.0f} {currency}/m²")
        console.print(f"  Max:     {max(pm2):,.0f} {currency}/m²")
        console.print(f"  Median:  {pm2_median:,.0f} {currency}/m²")
