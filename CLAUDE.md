# b-scrape

CLI scraper for bazos.sk/bazos.cz and nehnutelnosti.sk classified ads with price insights.

## Project structure

- `src/b_scrape/cli.py` — CLI entry point (argparse, --source flag for multi-portal, --export for file output)
- `src/b_scrape/client.py` — HTTP client (requests wrapper, headers, 1s rate limiting)
- `src/b_scrape/parser.py` — BeautifulSoup HTML parsing for bazos (listing cards, pagination, detail page m² extraction)
- `src/b_scrape/nehnutelnosti_parser.py` — JSON-LD parsing for nehnutelnosti.sk (RSC payload extraction)
- `src/b_scrape/models.py` — Dataclasses: Listing (source, area fields), SearchResult
- `src/b_scrape/urls.py` — URL builder for bazos (domain, category, search params, pagination)
- `src/b_scrape/nehnutelnosti_urls.py` — URL builder for nehnutelnosti.sk (path-based routing, flag mapping)
- `src/b_scrape/display.py` — Console table output (rich), grouped multi-source display, duplicate highlighting
- `src/b_scrape/export.py` — File export: CSV, XLSX (openpyxl), PDF (fpdf2) with summary stats

## CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `query` | `""` | Positional search query (e.g. `"2 izbový byt"`) |
| `--source` | `bazos` | Data source: `bazos`, `nehnutelnosti`, `all` |
| `--category` | `reality` | Bazos category subdomain slug |
| `--subcategory` | `""` | Subcategory path (e.g. `predam/byt`, `prenajmu/dom`) |
| `--location` | `""` | City name |
| `--radius` | `25` | Search radius in km (bazos only) |
| `--strict-location` | off | Exact city name match filter |
| `--zip` | `""` | Postcode filter (bazos only, e.g. `07101`) |
| `--price-from` | none | Minimum price |
| `--price-to` | none | Maximum price |
| `--site` | `bazos.sk` | Bazos TLD: `bazos.sk` or `bazos.cz` |
| `--filter` | `""` | Regex filter on listing titles |
| `--pages` | `1` | Pages to scrape (0 = all) |
| `--export` | `""` | Export formats: `csv`, `xlsx`, `pdf` (comma-separated) |
| `--output-dir` | `output` | Export directory |

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
- **Per listing**: `name`, `priceSpecification.price`, `floorSize.value` (m²), `url`; no address in JSON-LD (city backfilled from `--location`)
- **Property types**: `byty`, `2-izbove-byty`, `3-izbove-byty`, `domy`, `pozemky`
- **Transaction types**: `predaj`, `prenajom`
- **Flag mapping**: `--subcategory predam/byt` → `/byty/.../predaj`; query "2 izbový" → `/2-izbove-byty/`

## Key features

- **Multi-source**: `--source all` scrapes both portals and shows grouped results with combined summary
- **m² extraction**: bazos detail pages fetched for floor area; nehnutelnosti provides it in JSON-LD
- **Duplicate detection**: fuzzy title matching (difflib, ratio >= 0.7) highlights cross-source duplicates with `*`
- **Postcode filter**: `--zip` filters bazos listings by exact postcode (not available for nehnutelnosti)
- **Export**: `--export csv,xlsx,pdf` generates files in `--output-dir`

## Development

```bash
uv sync            # install deps
uv run b-scrape "2 izbový byt" --category reality --location Michalovce
uv run b-scrape "2 izbový byt" --source nehnutelnosti --subcategory predam/byt --location Michalovce
uv run b-scrape "2 izbový byt" --source all --subcategory predam/byt --location Michalovce --zip 07101 --pages 0
uv run b-scrape "2 izbový byt" --source all --subcategory predam/byt --location Michalovce --export csv,xlsx,pdf
```

## Commands

- `uv sync` — install/update dependencies
- `uv run b-scrape` — run the CLI
