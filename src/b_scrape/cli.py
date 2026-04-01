from __future__ import annotations

import argparse
import re

from rich.console import Console

from requests import HTTPError

from b_scrape.client import BazosClient
from b_scrape.display import print_multi_results, print_results
from b_scrape.models import SearchResult
from b_scrape.nehnutelnosti_parser import (
    parse_nehnutelnosti_listings,
    parse_nehnutelnosti_total_count,
)
from b_scrape.nehnutelnosti_urls import build_nehnutelnosti_url
from b_scrape.parser import parse_listings, parse_total_count
from b_scrape.urls import build_search_url


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="b-scrape",
        description="Search bazos.sk/bazos.cz and nehnutelnosti.sk classified ads.",
    )
    parser.add_argument(
        "query", nargs="?", default="", help="Search query (e.g. '2 izbový byt')"
    )
    parser.add_argument(
        "--category",
        default="reality",
        help="Category subdomain slug (default: reality)",
    )
    parser.add_argument(
        "--subcategory",
        default="",
        help="Subcategory path (e.g. 'prenajmu/byt', 'predam/dom')",
    )
    parser.add_argument("--location", default="", help="City name or postal code")
    parser.add_argument(
        "--radius", type=int, default=25, help="Search radius in km (default: 25, bazos only)"
    )
    parser.add_argument(
        "--strict-location",
        action="store_true",
        help="Only show listings where city matches --location exactly",
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
        help="Bazos site to search (default: bazos.sk)",
    )
    parser.add_argument(
        "--source",
        default="bazos",
        choices=["bazos", "nehnutelnosti", "all"],
        help="Data source (default: bazos)",
    )
    parser.add_argument(
        "--filter",
        default="",
        help="Regex pattern to filter listing titles (case-insensitive)",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Number of pages to scrape (default: 1, use 0 for all)",
    )
    return parser.parse_args(argv)


def _scrape_bazos(
    args: argparse.Namespace,
    client: BazosClient,
    console: Console,
    filter_re: re.Pattern | None,
    max_pages: int,
) -> SearchResult:
    result = SearchResult(
        query=args.query,
        category=args.category,
        location=args.location,
        site=args.site,
    )

    page = 0
    while max_pages == 0 or page < max_pages:
        url = build_search_url(
            category=args.category,
            site=args.site,
            subcategory=args.subcategory,
            query=args.query,
            location=args.location,
            radius=args.radius,
            price_from=args.price_from,
            price_to=args.price_to,
            page=page,
        )

        console.print(f"[dim]Fetching bazos page {page + 1}… {url}[/dim]")

        try:
            html = client.get(url)
        except HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                break
            console.print(f"[red]Error fetching page {page + 1}: {e}[/red]")
            break
        except Exception as e:
            console.print(f"[red]Error fetching page {page + 1}: {e}[/red]")
            break

        if page == 0:
            result.total_count = parse_total_count(html)

        listings = parse_listings(html, site=args.site)
        if not listings:
            break

        if args.strict_location and args.location:
            loc = args.location.lower()
            listings = [l for l in listings if l.city.lower() == loc]

        if filter_re:
            listings = [l for l in listings if filter_re.search(l.title)]

        result.listings.extend(listings)
        page += 1

    return result


def _scrape_nehnutelnosti(
    args: argparse.Namespace,
    client: BazosClient,
    console: Console,
    filter_re: re.Pattern | None,
    max_pages: int,
) -> SearchResult:
    if args.category != "reality":
        console.print(
            "[yellow]Warning: nehnutelnosti.sk only covers real estate. "
            f"--category '{args.category}' ignored.[/yellow]"
        )

    result = SearchResult(
        query=args.query,
        category="reality",
        location=args.location,
        site="nehnutelnosti.sk",
    )

    page = 1
    pages_fetched = 0
    while max_pages == 0 or pages_fetched < max_pages:
        url = build_nehnutelnosti_url(
            query=args.query,
            subcategory=args.subcategory,
            location=args.location,
            price_from=args.price_from,
            price_to=args.price_to,
            page=page,
        )

        console.print(f"[dim]Fetching nehnutelnosti page {page}… {url}[/dim]")

        try:
            html = client.get(url)
        except Exception as e:
            console.print(f"[red]Error fetching nehnutelnosti page {page}: {e}[/red]")
            break

        if pages_fetched == 0:
            result.total_count = parse_nehnutelnosti_total_count(html)

        listings = parse_nehnutelnosti_listings(html)
        if not listings:
            break

        if filter_re:
            listings = [l for l in listings if filter_re.search(l.title)]

        result.listings.extend(listings)
        pages_fetched += 1
        page += 1

    return result


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    console = Console()
    client = BazosClient()

    max_pages = args.pages if args.pages is not None else (0 if not args.query else 1)
    filter_re = re.compile(args.filter, re.IGNORECASE) if args.filter else None

    results: list[SearchResult] = []

    if args.source in ("bazos", "all"):
        results.append(_scrape_bazos(args, client, console, filter_re, max_pages))

    if args.source in ("nehnutelnosti", "all"):
        results.append(
            _scrape_nehnutelnosti(args, client, console, filter_re, max_pages)
        )

    if len(results) == 1:
        print_results(results[0], filter_pattern=args.filter)
    else:
        print_multi_results(results, filter_pattern=args.filter)


if __name__ == "__main__":
    main()
