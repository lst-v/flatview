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

_COMMANDS = {"search", "watch", "track"}


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


def _add_db_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override SQLite history path (default: ~/.local/share/flatview/flatview.db)",
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
        "--cma-segment",
        default=None,
        choices=["new", "resale"],
        help="Restrict CMA comparables to one segment (falls back to all when too few)",
    )
    parser.add_argument(
        "--no-store",
        action="store_true",
        help="Skip writing this run to the SQLite history store.",
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
    _add_db_flag(search)
    _add_common_flags(search)

    watch = sub.add_parser("watch", help="Manage saved searches for tracking")
    watch_sub = watch.add_subparsers(dest="watch_command", required=True)

    w_add = watch_sub.add_parser("add", help="Save a search to re-run on every `flatview track`")
    w_add.add_argument("name", help="Unique watch name (e.g. mi-2izb)")
    _add_search_flags(w_add)
    _add_db_flag(w_add)
    _add_common_flags(w_add)

    w_list = watch_sub.add_parser("list", help="List saved watches")
    w_list.add_argument("--all", action="store_true", help="Include inactive watches")
    _add_db_flag(w_list)
    _add_common_flags(w_list)

    w_remove = watch_sub.add_parser("remove", help="Remove a saved watch")
    w_remove.add_argument("name", help="Watch name to remove")
    _add_db_flag(w_remove)
    _add_common_flags(w_remove)

    track = sub.add_parser("track", help="Run all watches, detect new/changed/delisted listings")
    track.add_argument("--watch", default=None, help="Run only this watch (by name)")
    track.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and detect events but write nothing (no DB, no digest, no email)",
    )
    track.add_argument(
        "--no-email",
        action="store_true",
        help="Skip sending the email digest even when SMTP is configured",
    )
    track.add_argument(
        "--no-push",
        action="store_true",
        help="Skip the ntfy push notification even when [ntfy] is configured",
    )
    track.add_argument(
        "--config",
        default=None,
        help="Config file path (default: ~/.config/flatview/config.toml)",
    )
    _add_db_flag(track)
    _add_common_flags(track)

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

    # Analytics knobs ([analytics] iqr_k / cma_area_band) come from config.toml;
    # search must not die on e.g. an SMTP typo, so fall back to defaults loudly.
    from flatview.config import AnalyticsConfig, load_config
    from flatview.errors import ConfigError

    try:
        analytics_cfg = load_config().analytics
    except ConfigError as e:
        console.print(f"[yellow]{e} — using default analytics settings[/yellow]")
        analytics_cfg = AnalyticsConfig()

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
        n_flagged, _ = flag_outliers_iqr(all_listings, k=analytics_cfg.iqr_k)
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
                    cma_area_band=analytics_cfg.cma_area_band,
                    cma_segment=args.cma_segment,
                    history_conn=conn,
                    exclude_outliers=args.remove_outliers,
                    iqr_k=analytics_cfg.iqr_k,
                )
                console.print(f"[green]Exported HTML: {html_path}[/green]")
            else:
                console.print(f"[yellow]Unknown export format: {fmt}[/yellow]")

    if conn is not None:
        conn.close()
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    from pathlib import Path

    from rich.table import Table

    from flatview.errors import FlatviewError
    from flatview.storage import default_db_path, open_db
    from flatview.watches import Watch, add_watch, list_watches, remove_watch

    console = Console()
    db_path = Path(args.db_path) if args.db_path else default_db_path()
    conn = open_db(db_path)
    try:
        if args.watch_command == "add":
            watch = Watch(name=args.name, params=params_from_args(args))
            try:
                add_watch(conn, watch)
            except FlatviewError as e:
                console.print(f"[red]{e}[/red]")
                return 2
            console.print(f"[green]Added watch '{args.name}'.[/green]")

        elif args.watch_command == "list":
            watches = list_watches(conn, include_inactive=args.all)
            if not watches:
                console.print(
                    "[yellow]No watches saved. Add one with `flatview watch add`.[/yellow]"
                )
                return 0
            table = Table(title="Watches")
            table.add_column("Name", style="bold")
            table.add_column("Query")
            table.add_column("Source")
            table.add_column("Location")
            table.add_column("Subcategory")
            table.add_column("Price", justify="right")
            table.add_column("Pages", justify="right")
            table.add_column("Created", width=12)
            for w in watches:
                p = w.params
                price = ""
                if p.price_from is not None or p.price_to is not None:
                    price = f"{p.price_from or ''}–{p.price_to or ''}"
                name = w.name if w.active else f"[dim]{w.name} (inactive)[/dim]"
                table.add_row(
                    name,
                    p.query,
                    p.source,
                    p.location,
                    p.subcategory,
                    price,
                    "all" if p.pages in (0, None) else str(p.pages),
                    w.created_at[:10],
                )
            console.print(table)

        elif args.watch_command == "remove":
            if remove_watch(conn, args.name):
                console.print(f"[green]Removed watch '{args.name}'.[/green]")
            else:
                console.print(f"[red]No watch named '{args.name}'.[/red]")
                return 2

        return 0
    finally:
        conn.close()


def cmd_track(args: argparse.Namespace) -> int:
    from datetime import datetime
    from pathlib import Path

    from flatview.config import default_digest_dir, load_config
    from flatview.digest import (
        digest_subject,
        has_events,
        render_digest,
        render_digest_text,
        write_digest,
    )
    from flatview.errors import ConfigError, EmailError, NotifyError
    from flatview.track import run_track

    console = Console()
    try:
        config = load_config(Path(args.config) if args.config else None)
    except ConfigError as e:
        console.print(f"[red]{e}[/red]")
        return 2

    code, all_events = run_track(
        db_path=Path(args.db_path) if args.db_path else None,
        watch_name=args.watch,
        dry_run=args.dry_run,
        delist_after_days=config.tracking.delist_after_days,
        iqr_k=config.analytics.iqr_k,
        backup_keep=config.tracking.backup_keep,
    )

    for ev in all_events:
        if ev.error:
            console.print(f"[red]{ev.watch.name}: failed — {ev.error}[/red]")
        elif ev.is_baseline:
            console.print(
                f"[cyan]{ev.watch.name}[/cyan]: baseline run, "
                f"{ev.n_listings} listings recorded (new-listing alerts start next run)"
            )
        else:
            unique = f" ({ev.n_unique} unique)" if ev.n_unique != ev.n_listings else ""
            console.print(
                f"[cyan]{ev.watch.name}[/cyan]: {ev.n_listings} listings{unique} — "
                f"[green]{len(ev.new)} new[/green], "
                f"{len(ev.price_drops)} price drops, "
                f"{len(ev.delisted)} delisted, "
                f"{len(ev.bargains)} bargains"
            )
            if ev.trend and ev.trend.pm2_delta_pct is not None:
                console.print(
                    f"  [dim]trend: median €/m² {ev.trend.median_pm2_now:,.0f} "
                    f"({ev.trend.pm2_delta_pct:+.1f}% vs {ev.trend.period_days} d ago)[/dim]"
                )
    if args.dry_run:
        if all_events:
            console.print("[dim]Dry run: nothing was written.[/dim]")
        return code

    if all_events:
        now = datetime.now()
        html = render_digest(all_events, generated_at=now)
        digest_dir = config.tracking.digest_dir or default_digest_dir()
        digest_path = write_digest(html, digest_dir, now)
        console.print(f"[green]Digest written: {digest_path}[/green]")

        should_email = (
            config.smtp is not None
            and not args.no_email
            and (has_events(all_events) or not config.tracking.email_only_on_events)
        )
        if should_email:
            from flatview.emailer import send_html_email

            assert config.smtp is not None
            try:
                send_html_email(
                    smtp=config.smtp,
                    subject=digest_subject(all_events),
                    html=html,
                    text_fallback=render_digest_text(all_events),
                )
                console.print("[green]Digest email sent.[/green]")
            except EmailError as e:
                console.print(f"[red]{e}[/red]")
                console.print(f"[yellow]Digest file remains at {digest_path}.[/yellow]")
                code = code or 1

        # Push is event-driven by design: a "no changes" push is just noise.
        should_push = config.ntfy is not None and not args.no_push and has_events(all_events)
        if should_push:
            from flatview.notify import build_push_message, send_ntfy

            assert config.ntfy is not None
            try:
                send_ntfy(
                    config.ntfy,
                    title=digest_subject(all_events),
                    message=build_push_message(all_events),
                )
                console.print("[green]Push notification sent (ntfy).[/green]")
            except NotifyError as e:
                console.print(f"[red]{e}[/red]")
                code = code or 1

    # Dead-man's switch: ping after the whole run so a hung/broken schedule
    # (not just a failed scrape) surfaces in monitoring.
    if config.tracking.healthcheck_url:
        from flatview.notify import ping_healthcheck

        ping_healthcheck(config.tracking.healthcheck_url, ok=code == 0)
    return code


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    setup_logging(verbose=getattr(args, "verbose", False))

    if args.command == "search":
        code = cmd_search(args)
    elif args.command == "watch":
        code = cmd_watch(args)
    elif args.command == "track":
        code = cmd_track(args)
    else:  # pragma: no cover — argparse rejects unknown commands
        code = 2

    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
