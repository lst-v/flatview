# flatview

CLI scraper for Slovak and Czech real estate classified ads. Aggregates listings from [bazos.sk](https://www.bazos.sk)/[bazos.cz](https://www.bazos.cz) and [nehnutelnosti.sk](https://www.nehnutelnosti.sk) with price and price-per-m2 analysis.

## Features

- Search across **bazos.sk**, **bazos.cz**, and **nehnutelnosti.sk** — individually or combined
- **Price insights**: min, max, average, median for both price and price/m2
- **Floor area extraction**: from nehnutelnosti.sk JSON-LD and bazos detail pages
- **Duplicate detection**: fuzzy matching highlights listings that appear on multiple portals
- **Flexible filtering**: by location, postcode, price range, regex on titles
- **Export**: CSV, XLSX, and PDF output with summary statistics

## Installation

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/lst-v/flatview.git
cd flatview
uv sync
```

## Usage

```bash
# Search bazos.sk (default source)
uv run flatview "2 izbový byt" --subcategory predam/byt --location Michalovce

# Search nehnutelnosti.sk only
uv run flatview "2 izbový byt" --source nehnutelnosti --subcategory predam/byt --location Michalovce

# Combined search with postcode filter and all pages
uv run flatview "2 izbový byt" --source all --subcategory predam/byt \
  --location Michalovce --radius 0 --strict-location --zip 07101 --pages 0

# Export results to CSV and Excel
uv run flatview "2 izbový byt" --source all --subcategory predam/byt \
  --location Michalovce --export csv,xlsx

# Filter titles with regex
uv run flatview "2 izbový byt" --subcategory predam/byt --location Bratislava \
  --filter "rekonštruk"

# Search Czech bazos
uv run flatview "2+kk" --site bazos.cz --subcategory prodam/byt --location Praha
```

## CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `query` | | Search query (positional) |
| `--source` | `bazos` | `bazos`, `nehnutelnosti`, or `all` |
| `--category` | `reality` | Bazos category subdomain |
| `--subcategory` | | Path like `predam/byt`, `prenajmu/dom` |
| `--location` | | City name |
| `--radius` | `25` | Search radius in km (bazos only) |
| `--strict-location` | off | Exact city name match |
| `--zip` | | Postcode filter (bazos only) |
| `--price-from` | | Minimum price |
| `--price-to` | | Maximum price |
| `--site` | `bazos.sk` | `bazos.sk` or `bazos.cz` |
| `--filter` | | Regex filter on titles |
| `--pages` | `1` | Pages to scrape (`0` = all) |
| `--export` | | Export: `csv`, `xlsx`, `pdf` (comma-separated) |
| `--output-dir` | `output` | Export directory |

## How it works

**bazos.sk/cz**: Scrapes HTML listing cards from search results. Fetches each listing's detail page to extract floor area (m2) from the description. Supports subdomain-based categories (`reality.bazos.sk`, `auto.bazos.sk`, etc.).

**nehnutelnosti.sk**: Extracts structured JSON-LD data from Next.js server-rendered pages. Floor area and price are available directly in the search results without needing detail page requests.

**Combined mode** (`--source all`): Runs both scrapers, displays results grouped by source, then shows combined price statistics. Cross-source duplicates are detected via fuzzy title matching and highlighted with `*`.

## License

[MIT](LICENSE)
