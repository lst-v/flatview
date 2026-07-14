# flatview

Market-tracking CLI for bazos.sk/bazos.cz, nehnutelnosti.sk and topreality.sk classified ads: one-shot search with price insights, saved-search watches, scheduled tracking with event detection, and email/HTML digests.

## Project structure

- `src/flatview/cli.py` — CLI entry point: subcommands `search` (default, legacy shim prepends it), `watch add|list|remove`, `track`; `params_from_args`; per-command `cmd_*` functions
- `src/flatview/scrape.py` — portal scraping decoupled from argparse: frozen `SearchParams`, `scrape()` dispatch, `scrape_bazos/nehnutelnosti/topreality`, shared `_apply_filters`, HTML-drift warning
- `src/flatview/client.py` — HTTP client (requests wrapper, headers, 1s rate limiting, urllib3 Retry backoff on 429/5xx, configurable timeout)
- `src/flatview/parser.py` — BeautifulSoup HTML parsing for bazos (listing cards, pagination, detail page m² extraction)
- `src/flatview/nehnutelnosti_parser.py` — JSON-LD parsing for nehnutelnosti.sk (RSC payload extraction)
- `src/flatview/topreality_parser.py` — BeautifulSoup HTML parsing for topreality.sk (listing cards, area extraction)
- `src/flatview/urls.py`, `nehnutelnosti_urls.py`, `topreality_urls.py` — per-portal URL builders
- `src/flatview/models.py` — Dataclasses: `Listing` (segment, is_outlier, outlier_side, first_seen, previous_price), `SearchResult` (error field for fetch failures)
- `src/flatview/analytics.py` — `compute_percentiles` (linear interpolation), `compute_stats`, `flag_outliers_iqr(k=1.5)` two-sided (bargain/overpriced), `iqr_fence`, `classify_segment`/`annotate_segments` (new/resale), `price_per_m2` (single source of truth), `cheapest_by_pm2`. Placeholder prices (≤ 1 €, "Rezervované" token ads) are excluded from all stats and outlier detection
- `src/flatview/storage.py` — SQLite at `~/.local/share/flatview/flatview.db` (XDG). Tables: `listings`, `price_history`, `watches`, `watch_runs`, `watch_listings`. Upserts, price history, run recording, delist queries; `backup_db` (daily rotated snapshot via SQLite backup API)
- `src/flatview/dedup.py` — cross-source entity resolution: `is_duplicate` (area/price/city match with title guard; hard price/area contradictions veto), `find_duplicate_groups` (union-find), `select_canonical` (richest listing wins), `dedupe`. Replaces the old title-ratio-only heuristic
- `src/flatview/watches.py` — `Watch` dataclass wrapping `SearchParams`; add/get/list/remove
- `src/flatview/track.py` — tracking pipeline: `run_watch` (events: new/price drops/increases/delisted/bargains/overpriced + `trend`), `run_track` (exit codes 0/1/2), `WatchEvents`/`PriceChange`/`DelistedInfo`
- `src/flatview/trends.py` — market trends from stored history: `snapshot` (as-of-date median €/m² + active count; price = latest observation ≤ date, active = membership window covers date, cross-posts collapsed by rounded price+area key), `compute_trend` → `TrendSummary` (deltas vs 7 d ago, activity from `watch_runs`, `days_on_market_stats`, `price_cut_stats`, `rolling_median_pm2` 30-d series). Computed in `run_watch` unless dry-run; failures logged, never abort the run. `median_pm2_series_for_listings` — as-of series scoped to an explicit listing set (the report chart: only the current query's entities replay, so other searches in the DB can't bend it; survivor-biased for old dates by construction)
- `src/flatview/config.py` — `~/.config/flatview/config.toml` (tomllib): `SmtpConfig`, `NtfyConfig`, `TrackingConfig`, `AnalyticsConfig` (`iqr_k`, `cma_area_band` — validated, used by both search and track); `FLATVIEW_SMTP_PASSWORD` / `FLATVIEW_NTFY_TOKEN` env overrides
- `src/flatview/digest.py` — email-safe HTML digest (inline CSS, no JS) + text fallback; per-watch sections incl. "Lowest €/m² right now" (top 5 with Δ vs median — low-end visibility even when nothing crosses the IQR fence) and "Market trend" (deltas vs 7 d ago, DOM, price cuts, 30-d series; hidden on baseline runs); `write_digest` → timestamped + `latest.html` in `~/.local/share/flatview/digests/`
- `src/flatview/emailer.py` — SMTP send via stdlib `EmailMessage`; raises `EmailError`
- `src/flatview/notify.py` — ntfy push: `send_ntfy` (JSON publish to server root — headers are latin-1 only, JSON keeps diacritics), `build_push_message` (phone-sized, capped lines); raises `NotifyError`. `ping_healthcheck` (dead-man's switch, never raises)
- `src/flatview/display.py` — console tables (rich), grouped multi-source display, duplicate highlighting, ↓/↑ outlier markers
- `src/flatview/export.py` — CSV, XLSX (openpyxl), PDF (fpdf2). Listing rows are a full dump with `*crosspost` markers (CSV/XLSX); summary stats count each flat once with an explanatory note
- `src/flatview/html_report.py` — browser HTML report (Plotly CDN), card-based minimal styling: stats, charts, outlier sections, comparables; CMA mode leads with a hero recommendation range + metric chips, optional segment-restricted comps (`cma_segment`, ≥4 or falls back), asking-price disclaimer. Stats/charts/outliers/CMA run on the deduped pool (outliers re-flagged there); header shows raw vs unique counts. History chart = as-of median €/m² replayed over this query's listings only (never grouped by raw observation date — that biases toward whatever changed that day)
- `src/flatview/errors.py` — `FlatviewError` / `ScrapeError` / `ConfigError` / `EmailError` / `NotifyError`
- `src/flatview/log.py` — `setup_logging`: RichHandler console + rotating file log at `~/.local/state/flatview/flatview.log`

## CLI

Subcommands: `search` (default — bare `flatview "query" --flags` still works via shim), `watch add|list|remove`, `track`. All accept `-v` (debug logging) and `--db-path`.

Search flags (shared by `search` and `watch add`):

| Flag | Default | Description |
|------|---------|-------------|
| `query` | `""` | Positional search query (e.g. `"2 izbový byt"`) |
| `--source` | `bazos` | Data source: `bazos`, `nehnutelnosti`, `topreality`, `all` |
| `--category` | `reality` | Bazos category subdomain slug |
| `--subcategory` | `""` | Subcategory path (e.g. `predam/byt`, `prenajmu/dom`) |
| `--location` | `""` | City name |
| `--radius` | `25` | Search radius in km (bazos only) |
| `--strict-location` | off | Exact city name match filter |
| `--zip` | `""` | Postcode filter (bazos only, e.g. `07101`) |
| `--price-from` / `--price-to` | none | Price range |
| `--site` | `bazos.sk` | Bazos TLD: `bazos.sk` or `bazos.cz` |
| `--filter` | `""` | Regex filter on listing titles |
| `--pages` | `1` with query, all without | Pages to scrape (0 = all; watches store 0 by default) |

`search`-only: `--export csv,xlsx,pdf,html`, `--output-dir` (default `output`), `--report full|cma`, `--cma-area FLOAT`, `--cma-segment new|resale` (restrict comps, falls back below 4), `--remove-outliers`, `--no-store`.
`track`-only: `--watch NAME`, `--dry-run` (no writes/email/push), `--no-email`, `--no-push`, `--config PATH`.

## Tracking pipeline (`flatview track`)

- Watches stored in the `watches` table (SearchParams columns 1:1); runs audited in `watch_runs` (status: running/ok/empty/error)
- Per-watch listing membership in `watch_listings` (PK watch_id+source+listing_key, first/last_matched, delisted_at) — NEW/DELISTED are per watch, overlapping watches don't interfere
- **NEW** = key not yet in watch_listings; the first successful run is a *baseline* and suppresses the NEW flood
- **Price drop/increase** = current price vs `listings.last_price`, read before upsert
- **Delisted** = `last_matched` older than `delist_after_days` (default 2) — checked only after a successful non-empty scrape; empty/error runs never delist (protects against network failure and HTML drift)
- Exit codes: 0 all ok, 1 ≥1 watch failed, 2 usage/config error. `SearchResult.error` distinguishes "unreachable" from "genuinely empty"
- Ops: daily rotated DB backup before each non-dry run (`tracking.backup_keep`, 0 disables); `tracking.healthcheck_url` pinged after every run (`/fail` suffix on failure, ping errors never change the exit code)
- Digest always written unless `--dry-run`; email only when SMTP configured ∧ not `--no-email` ∧ (events or `email_only_on_events=false`); ntfy push only when `[ntfy]` configured ∧ not `--no-push` ∧ events (quiet runs never push)
- Trend per watch (`WatchEvents.trend`): median €/m² and active count vs 7 d ago, 30-d rolling median series, median days-on-market of recent delistings, price-cut share/size; current run's events folded into the activity window before the run row is recorded
- Scheduling: launchd plist or crontab (see README "Scheduling on macOS")

## How bazos works

- **Subdomain categories**: `{category}.bazos.{tld}` (e.g. `reality.bazos.sk`)
- **Pagination**: path-based offset in increments of 20 (`/20/`, `/40/`, etc.)
- **Search params**: `hledat`, `hlokalita`, `humkreis`, `cenaod`/`cenado`
- **Encoding**: UTF-8
- **SK vs CZ**: identical HTML structure, different category slugs and currency (EUR/€ vs CZK/Kč)
- **Listing card CSS**: `div.inzeraty.inzeratyflex` container, `h2.nadpis a` title, `div.inzeratycena` price, `div.inzeratylok` location (city`<br>`postcode), `div.inzeratyview` views
- **Total count**: in `div.listainzerat div.inzeratynadpis`, pattern "z {N}"
- **Detail pages**: `div.popisdetail` contains listing description; m² extracted via regex `(\d+(?:[.,]\d+)?)\s*m[²2]`
- **Deleted listings**: detected by "vymazaný" in `div.maincontent` first 100 chars

## How nehnutelnosti.sk works

- **URL pattern**: `https://www.nehnutelnosti.sk/vysledky/{property_type}/{location}/{transaction}` (order matters!)
- **Pagination**: `?page=N` query param, 30 items/page, starts at 1
- **Data source**: JSON-LD schema.org graph embedded in Next.js RSC `self.__next_f.push()` script chunks
- **Graph path**: `@graph` → `SearchResultsPage` → `mainEntity` (ItemList) → `itemListElement`
- **Per listing**: `name`, `priceSpecification.price`, `floorSize.value` (m²), `url`; no address in JSON-LD (city backfilled from `--location`); listing id is a URL slug string
- **Property types**: `byty`, `2-izbove-byty`, `3-izbove-byty`, `domy`, `pozemky`
- **Transaction types**: `predaj`, `prenajom`
- **Flag mapping**: `--subcategory predam/byt` → `/byty/.../predaj`; query "2 izbový" → `/2-izbove-byty/`

## How topreality.sk works

- **URL pattern**: `https://www.topreality.sk/vyhladavanie-nehnutelnosti.html?searchType=string&fromForm=1&q={query}&form={transaction}&type[]={property_type}&obec={location_id}`
- **Pagination**: page number in URL path: `-N` suffix (e.g. `/vyhladavanie-nehnutelnosti-2.html`), ~16 items/page, starts at 1
- **Data source**: server-rendered HTML, parsed with BeautifulSoup
- **Listing card CSS**: `div.row.estate` container with `data-idinz` attribute, `.card-title a` title/URL, `.price` price, `.location-city` city, `.area-floor` usable area (m²), `.area-building` built area fallback
- **Location resolution**: `--location` resolved to district ID via AJAX endpoint `/user/new_estate/searchAjax.php?term={name}`, returns IDs like `d807-Okres Michalovce`
- **Free-text search**: supported via `q` query param
- **Form params**: `searchType=string`, `fromForm=1` (required); `form` = transaction type (1=Predám, 3=Prenájom); `type[]` = property type ID (103=2-izb byt, 204=dom, etc.); `obec` = district ID; `cena_od`/`cena_do`
- **Flag mapping**: `--subcategory predam/byt` → `form=1&type[]=103`
- **Limitations**: no postcode, no date in search results, no views count, no radius

## Key features

- **Multi-source**: `--source all` scrapes all portals and shows grouped results with combined summary
- **m² extraction**: bazos detail pages fetched for floor area; nehnutelnosti provides it in JSON-LD; topreality provides it in HTML
- **Duplicate detection**: entity resolution in `dedup.py` (area+price+city with title guard, title-only fallback ≥ 0.7) marks cross-source duplicates with `*`; combined-summary stats, track analytics (outliers/cheapest/stats), NEW alerts, HTML report (stats/charts/CMA), and export summaries all count each flat once — a cross-post to a second portal does not alert
- **Two-sided outliers**: k×IQR fence on €/m² (k = `analytics.iqr_k`, default 1.5); below = bargain (green ↓), above = overpriced (red ↑); surfaced in console, exports, HTML report, digest. CMA comparable band likewise configurable (`analytics.cma_area_band`)
- **Market trends**: per-watch deltas vs 7 days ago (median €/m², active listings), 30-day median series, days-on-market, price-cut frequency — reconstructed from `price_history`/`watch_listings`/`watch_runs`, in the digest and track console
- **Push notifications**: ntfy channel (`[ntfy]` in config.toml) — event-driven push to phone alongside the email digest
- **Postcode filter**: `--zip` filters bazos listings by exact postcode (not available for nehnutelnosti/topreality)
- **Export**: `--export csv,xlsx,pdf,html` generates files in `--output-dir`

## Development

```bash
uv sync                                # install deps (incl. ruff, mypy, pytest)
uv run pytest                          # tests
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run mypy src/flatview               # type check
uv run flatview "2 izbový byt" --subcategory predam/byt --location Michalovce
uv run flatview search "2 izbový byt" --source all --subcategory predam/byt --location Michalovce --export html
uv run flatview watch add mi-2izb "2 izbový byt" --source all --subcategory predam/byt --location Michalovce
uv run flatview track --dry-run -v
```

CI (`.github/workflows/ci.yml`) runs ruff + mypy + pytest on Python 3.12–3.14. Tests never hit the network — scrapers are tested with fixture HTML and a fake client; track with monkeypatched scrape.
