from __future__ import annotations

from rich.console import Console
from rich.table import Table

from b_scrape.models import SearchResult


def print_results(result: SearchResult) -> None:
    """Print search results as a rich table with summary stats."""
    console = Console()

    if not result.listings:
        console.print("[yellow]No listings found.[/yellow]")
        return

    # Header
    header_parts = [f"[bold]{result.query}[/bold]"]
    if result.category:
        header_parts.append(f"in [cyan]{result.category}[/cyan]")
    if result.location:
        header_parts.append(f"near [cyan]{result.location}[/cyan]")
    header_parts.append(f"on [cyan]{result.site}[/cyan]")
    console.print(" ".join(header_parts))

    if result.total_count is not None:
        console.print(f"Total results: {result.total_count}")
    console.print(f"Showing: {len(result.listings)} listings\n")

    # Table
    table = Table(show_lines=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", max_width=50)
    table.add_column("Price", justify="right")
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

        table.add_row(
            str(i),
            listing.title,
            price_str,
            location,
            listing.date,
        )

    console.print(table)

    # Summary stats
    prices = [l.price for l in result.listings if l.price is not None]
    if prices:
        currency = result.listings[0].currency
        avg = sum(prices) / len(prices)
        console.print(f"\n[bold]Price summary[/bold] ({len(prices)} with price):")
        console.print(f"  Average: {avg:,.0f} {currency}")
        console.print(f"  Min:     {min(prices):,.0f} {currency}")
        console.print(f"  Max:     {max(prices):,.0f} {currency}")
        median = sorted(prices)[len(prices) // 2]
        console.print(f"  Median:  {median:,.0f} {currency}")
