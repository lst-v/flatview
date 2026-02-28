# b-scrape

CLI scraper for bazos.sk/bazos.cz classified ads with price insights.

## Project structure

- `src/b_scrape/cli.py` — CLI entry point (argparse)
- `src/b_scrape/client.py` — HTTP client (requests wrapper, headers, rate limiting)
- `src/b_scrape/parser.py` — BeautifulSoup HTML parsing (listing cards, pagination)
- `src/b_scrape/models.py` — Dataclasses: Listing, SearchResult
- `src/b_scrape/urls.py` — URL builder (domain, category, search params, pagination)
- `src/b_scrape/display.py` — Console table output (rich)

## How bazos works

- **Subdomain categories**: `{category}.bazos.{tld}` (e.g. `reality.bazos.sk`)
- **Pagination**: path-based offset in increments of 20 (`/20/`, `/40/`, etc.)
- **Search params**: `hledat`, `hlokalita`, `humkreis`, `cenaod`/`cenado`
- **Encoding**: UTF-8
- **SK vs CZ**: identical HTML structure, different category slugs and currency (EUR/€ vs CZK/Kč)
- **Listing card CSS**: `div.inzeraty.inzeratyflex` container, `h2.nadpis a` title, `div.inzeratycena` price, `div.inzeratylok` location (city`<br>`postcode), `div.inzeratyview` views
- **Total count**: in `div.listainzerat div.inzeratynadpis`, pattern "z {N}"

## Development

```bash
uv sync            # install deps
uv run b-scrape "2 izbový byt" --category reality --location Michalovce
```

## Commands

- `uv sync` — install/update dependencies
- `uv run b-scrape` — run the CLI
