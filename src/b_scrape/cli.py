from __future__ import annotations

import argparse
import sys

from rich.console import Console

from b_scrape.client import BazosClient
from b_scrape.display import print_results
from b_scrape.models import SearchResult
from b_scrape.parser import parse_listings, parse_total_count
from b_scrape.urls import build_search_url


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="b-scrape",
        description="Search bazos.sk/bazos.cz classified ads and get price insights.",
    )
    parser.add_argument("query", help="Search query (e.g. '2 izbový byt')")
    parser.add_argument(
        "--category",
        default="reality",
        help="Category subdomain slug (default: reality)",
    )
    parser.add_argument("--location", default="", help="City name or postal code")
    parser.add_argument(
        "--radius", type=int, default=25, help="Search radius in km (default: 25)"
    )
    parser.add_argument(
        "--price-from", type=int, default=None, help="Minimum price filter"
    )
    parser.add_argument(
        "--price-to", type=int, default=None, help="Maximum price filter"
    )
    parser.add_argument(
        "--site",
        default="bazos.sk",
        choices=["bazos.sk", "bazos.cz"],
        help="Site to search (default: bazos.sk)",
    )
    parser.add_argument(
        "--pages", type=int, default=1, help="Number of pages to scrape (default: 1)"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    console = Console()
    client = BazosClient()

    result = SearchResult(
        query=args.query,
        category=args.category,
        location=args.location,
        site=args.site,
    )

    for page in range(args.pages):
        url = build_search_url(
            category=args.category,
            site=args.site,
            query=args.query,
            location=args.location,
            radius=args.radius,
            price_from=args.price_from,
            price_to=args.price_to,
            page=page,
        )

        console.print(f"[dim]Fetching page {page + 1}… {url}[/dim]")

        try:
            html = client.get(url)
        except Exception as e:
            console.print(f"[red]Error fetching page {page + 1}: {e}[/red]")
            break

        if page == 0:
            result.total_count = parse_total_count(html)

        listings = parse_listings(html, site=args.site)
        if not listings:
            break
        result.listings.extend(listings)

    print_results(result)


if __name__ == "__main__":
    main()
