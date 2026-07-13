from __future__ import annotations

import argparse
import re
from datetime import date

from requests import HTTPError
from rich.console import Console

from flatview.client import BazosClient
from flatview.display import print_multi_results, print_results
from flatview.models import SearchResult
from flatview.nehnutelnosti_parser import (
    parse_nehnutelnosti_listings,
    parse_nehnutelnosti_total_count,
)
from flatview.nehnutelnosti_urls import build_nehnutelnosti_url
from flatview.parser import parse_detail, parse_listings, parse_total_count
from flatview.topreality_parser import (
    parse_topreality_listings,
    parse_topreality_total_count,
)
from flatview.topreality_urls import build_topreality_url, resolve_location
from flatview.urls import build_search_url


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="flatview",
        description="Search bazos.sk/bazos.cz, nehnutelnosti.sk and topreality.sk classified ads.",
    )
    parser.add_argument("query", nargs="?", default="", help="Search query (e.g. '2 izbový byt')")
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
    parser.add_argument("--price-from", type=int, default=None, help="Minimum price filter")
    parser.add_argument("--price-to", type=int, default=None, help="Maximum price filter")
    parser.add_argument(
        "--site",
        default="bazos.sk",
        choices=["bazos.sk", "bazos.cz"],
        help="Bazos site to search (default: bazos.sk)",
    )
    parser.add_argument(
        "--source",
        default="bazos",
        choices=["bazos", "nehnutelnosti", "topreality", "all"],
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
        help="Export formats: csv, xlsx, pdf, html (comma-separated)",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Output directory for exports (default: output/)",
    )
    parser.add_argument(
        "--remove-outliers",
        action="store_true",
        help=(
            "Exclude IQR outliers (on EUR/m²) from stats and charts. Listings still shown, tagged."
        ),
    )
    parser.add_argument(
        "--report",
        default="full",
        choices=["full", "cma"],
        help="HTML report mode (default: full). 'cma' produces an agent-style comparable analysis.",
    )
    parser.add_argument(
        "--cma-area",
        type=float,
        default=None,
        help="Target floor area (m²) for --report cma. Required when --report cma.",
    )
    parser.add_argument(
        "--no-store",
        action="store_true",
        help="Skip writing this run to the SQLite history store.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override SQLite history path (default: ~/.local/share/flatview/flatview.db)",
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
        listing.url = listing.url.replace(f"://www.{args.site}", f"://{args.category}.{args.site}")
        detail_url = listing.url
        try:
            console.print(f"[dim]  Detail {i}/{total}…[/dim]")
            detail_html = client.get(detail_url)
            area, description = parse_detail(detail_html)
            if area:
                listing.area = area
            if description:
                listing.description = description
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
        console.print(
            "[yellow]Warning: --zip filter not supported for nehnutelnosti.sk "
            "(no postcode data).[/yellow]"
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


def _scrape_topreality(
    args: argparse.Namespace,
    client: BazosClient,
    console: Console,
    filter_re: re.Pattern | None,
    max_pages: int,
) -> SearchResult:
    if args.category != "reality":
        console.print(
            "[yellow]Warning: topreality.sk only covers real estate. "
            f"--category '{args.category}' ignored.[/yellow]"
        )
    if args.zip:
        console.print(
            "[yellow]Warning: --zip filter not supported for topreality.sk "
            "(no postcode data).[/yellow]"
        )

    result = SearchResult(
        query=args.query,
        category="reality",
        location=args.location,
        site="topreality.sk",
    )

    # Resolve location name to topreality district ID
    location_id = ""
    if args.location:
        console.print(f"[dim]Resolving topreality location for '{args.location}'…[/dim]")
        location_id = resolve_location(args.location)
        if location_id:
            console.print(f"[dim]Resolved to: {location_id}[/dim]")
        else:
            console.print(
                f"[yellow]Warning: could not resolve location '{args.location}' "
                "on topreality.sk[/yellow]"
            )

    page = 1
    pages_fetched = 0
    while max_pages == 0 or pages_fetched < max_pages:
        url = build_topreality_url(
            query=args.query,
            subcategory=args.subcategory,
            location_id=location_id,
            price_from=args.price_from,
            price_to=args.price_to,
            page=page,
        )

        console.print(f"[dim]Fetching topreality page {page}… {url}[/dim]")

        try:
            html = client.get(url)
        except Exception as e:
            console.print(f"[red]Error fetching topreality page {page}: {e}[/red]")
            break

        if pages_fetched == 0:
            result.total_count = parse_topreality_total_count(html)

        listings = parse_topreality_listings(html)
        if not listings:
            break

        if args.location:
            for listing in listings:
                if not listing.city:
                    listing.city = args.location

        if args.strict_location and args.location:
            loc = args.location.lower()
            listings = [l for l in listings if l.city.lower() == loc]

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

    if args.report == "cma" and args.cma_area is None:
        console.print("[red]--report cma requires --cma-area FLOAT[/red]")
        raise SystemExit(2)

    max_pages = args.pages if args.pages is not None else (0 if not args.query else 1)
    filter_re = re.compile(args.filter, re.IGNORECASE) if args.filter else None

    results: list[SearchResult] = []

    if args.source in ("bazos", "all"):
        results.append(_scrape_bazos(args, client, console, filter_re, max_pages))

    if args.source in ("nehnutelnosti", "all"):
        results.append(_scrape_nehnutelnosti(args, client, console, filter_re, max_pages))

    if args.source in ("topreality", "all"):
        results.append(_scrape_topreality(args, client, console, filter_re, max_pages))

    all_listings = [l for r in results for l in r.listings]

    # Post-scrape pipeline: segment, persist, flag outliers.
    from flatview.analytics import annotate_segments, flag_outliers_iqr

    annotate_segments(all_listings)

    conn = None
    if all_listings and not args.no_store:
        from pathlib import Path

        from flatview.storage import (
            backfill_history,
            default_db_path,
            open_db,
            upsert_listings,
        )

        db_path = Path(args.db_path) if args.db_path else default_db_path()
        try:
            conn = open_db(db_path)
            upsert_listings(conn, all_listings)
            backfill_history(conn, all_listings)
        except Exception as e:
            console.print(f"[yellow]Storage disabled: {e}[/yellow]")
            conn = None

    if all_listings:
        n_flagged, _ = flag_outliers_iqr(all_listings)
        if n_flagged:
            console.print(f"[yellow]Flagged {n_flagged} outliers on EUR/m² (IQR fence).[/yellow]")

    if len(results) == 1:
        print_results(results[0], filter_pattern=args.filter, exclude_outliers=args.remove_outliers)
    else:
        print_multi_results(
            results, filter_pattern=args.filter, exclude_outliers=args.remove_outliers
        )

    # Export
    if args.export and all_listings:
        from flatview.export import export_csv, export_pdf, export_xlsx
        from flatview.html_report import render_report

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
            elif fmt == "html":
                from pathlib import Path

                suffix = "_cma" if args.report == "cma" else ""
                html_path = Path(f"{base}{suffix}.html")
                render_report(
                    all_listings,
                    query=args.query,
                    location=args.location,
                    sources=[r.site for r in results if r.listings],
                    out_path=html_path,
                    mode=args.report,
                    cma_target_area=args.cma_area,
                    history_conn=conn,
                    exclude_outliers=args.remove_outliers,
                )
                console.print(f"[green]Exported HTML: {html_path}[/green]")
            else:
                console.print(f"[yellow]Unknown export format: {fmt}[/yellow]")

    if conn is not None:
        conn.close()


if __name__ == "__main__":
    main()
