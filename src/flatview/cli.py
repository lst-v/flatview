from __future__ import annotations

import argparse
import re
from datetime import date

from rich.console import Console

from requests import HTTPError

from flatview.client import BazosClient
from flatview.display import print_multi_results, print_results
from flatview.models import SearchResult
from flatview.nehnutelnosti_parser import (
    parse_nehnutelnosti_listings,
    parse_nehnutelnosti_total_count,
)
from flatview.nehnutelnosti_urls import build_nehnutelnosti_url
from flatview.parser import parse_detail_area, parse_listings, parse_total_count
from flatview.urls import build_search_url


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="flatview",
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
        "--zip",
        default="",
        help="Filter listings by postcode (bazos only, exact match)",
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
    parser.add_argument(
        "--export",
        default="",
        help="Export formats: csv, xlsx, pdf (comma-separated, e.g. 'csv,xlsx')",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Output directory for exports (default: output/)",
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

        if args.zip:
            zip_norm = args.zip.replace(" ", "")
            listings = [l for l in listings if l.postcode.replace(" ", "") == zip_norm]

        if filter_re:
            listings = [l for l in listings if filter_re.search(l.title)]

        result.listings.extend(listings)
        page += 1

    # Fetch detail pages for m² data
    total = len(result.listings)
    if total:
        console.print(f"[dim]Fetching bazos detail pages for m² data ({total} listings)…[/dim]")
    for i, listing in enumerate(result.listings, 1):
        if not listing.url:
            continue
        # Fix subdomain: detail URLs default to www.bazos.xx but need category subdomain
        detail_url = listing.url.replace(
            f"://www.{args.site}", f"://{args.category}.{args.site}"
        )
        try:
            console.print(f"[dim]  Detail {i}/{total}…[/dim]")
            detail_html = client.get(detail_url)
            area = parse_detail_area(detail_html)
            if area:
                listing.area = area
        except Exception:
            pass

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
    if args.zip:
        console.print("[yellow]Warning: --zip filter not supported for nehnutelnosti.sk (no postcode data).[/yellow]")

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

        if args.location:
            for listing in listings:
                if not listing.city:
                    listing.city = args.location

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

    # Export
    if args.export:
        from flatview.export import export_csv, export_pdf, export_xlsx

        all_listings = [l for r in results for l in r.listings]
        if not all_listings:
            return

        formats = [f.strip().lower() for f in args.export.split(",")]
        slug = re.sub(r"[^\w]+", "_", f"{args.query}_{args.location}".strip("_"))[:40]
        base = f"{args.output_dir}/{slug}_{date.today().isoformat()}"

        for fmt in formats:
            if fmt == "csv":
                path = f"{base}.csv"
                export_csv(all_listings, path)
                console.print(f"[green]Exported CSV: {path}[/green]")
            elif fmt == "xlsx":
                path = f"{base}.xlsx"
                export_xlsx(all_listings, path)
                console.print(f"[green]Exported XLSX: {path}[/green]")
            elif fmt == "pdf":
                path = f"{base}.pdf"
                title = f"{args.query} - {args.location} - {date.today().isoformat()}"
                export_pdf(all_listings, path, title=title)
                console.print(f"[green]Exported PDF: {path}[/green]")
            else:
                console.print(f"[yellow]Unknown export format: {fmt}[/yellow]")


if __name__ == "__main__":
    main()
