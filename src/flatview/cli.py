from __future__ import annotations

import argparse
import re
import sys
from datetime import date

from rich.console import Console

from flatview.client import BazosClient
from flatview.display import print_multi_results, print_results
from flatview.log import setup_logging
from flatview.models import SearchResult
from flatview.scrape import SearchParams, scrape

_COMMANDS = {"search"}


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show debug output (per-request logs, detail-page progress)",
    )


def _add_search_flags(parser: argparse.ArgumentParser) -> None:
    """Flags shared by `search` and `watch add` — they define what to scrape."""
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


def _add_output_flags(parser: argparse.ArgumentParser) -> None:
    """Flags specific to `search` — display, export, and storage behavior."""
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flatview",
        description="Search bazos.sk/bazos.cz, nehnutelnosti.sk and topreality.sk classified ads.",
    )
    sub = parser.add_subparsers(dest="command")

    search = sub.add_parser("search", help="One-shot search across portals (default command)")
    _add_search_flags(search)
    _add_output_flags(search)
    _add_common_flags(search)

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)
    # Legacy shim: bare `flatview "query" --flags` behaves as `flatview search …`.
    if not argv or (argv[0] not in _COMMANDS and argv[0] not in ("-h", "--help")):
        argv = ["search", *argv]
    return build_parser().parse_args(argv)


def params_from_args(args: argparse.Namespace) -> SearchParams:
    return SearchParams(
        query=args.query,
        source=args.source,
        site=args.site,
        category=args.category,
        subcategory=args.subcategory,
        location=args.location,
        radius=args.radius,
        strict_location=args.strict_location,
        zip_code=args.zip,
        price_from=args.price_from,
        price_to=args.price_to,
        title_filter=args.filter,
        pages=args.pages,
    )


def cmd_search(args: argparse.Namespace) -> int:
    console = Console()

    if args.report == "cma" and args.cma_area is None:
        console.print("[red]--report cma requires --cma-area FLOAT[/red]")
        return 2

    client = BazosClient()
    results: list[SearchResult] = scrape(params_from_args(args), client)
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
    return 0


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    setup_logging(verbose=getattr(args, "verbose", False))

    if args.command == "search":
        code = cmd_search(args)
    else:  # pragma: no cover — argparse rejects unknown commands
        code = 2

    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
