# b-scrape

CLI scraper for bazos.sk/bazos.cz and nehnutelnosti.sk classified ads with price insights.

## Project structure

- `src/b_scrape/cli.py` — CLI entry point (argparse, --source flag for multi-portal)
- `src/b_scrape/client.py` — HTTP client (requests wrapper, headers, rate limiting)
- `src/b_scrape/parser.py` — BeautifulSoup HTML parsing for bazos (listing cards, pagination)
- `src/b_scrape/nehnutelnosti_parser.py` — JSON-LD parsing for nehnutelnosti.sk (RSC payload extraction)
- `src/b_scrape/models.py` — Dataclasses: Listing (source, area fields), SearchResult
- `src/b_scrape/urls.py` — URL builder for bazos (domain, category, search params, pagination)
- `src/b_scrape/nehnutelnosti_urls.py` — URL builder for nehnutelnosti.sk (path-based routing, flag mapping)
- `src/b_scrape/display.py` — Console table output (rich), grouped multi-source display

## How bazos works

- **Subdomain categories**: `{category}.bazos.{tld}` (e.g. `reality.bazos.sk`)
- **Pagination**: path-based offset in increments of 20 (`/20/`, `/40/`, etc.)
- **Search params**: `hledat`, `hlokalita`, `humkreis`, `cenaod`/`cenado`
- **Encoding**: UTF-8
- **SK vs CZ**: identical HTML structure, different category slugs and currency (EUR/€ vs CZK/Kč)
- **Listing card CSS**: `div.inzeraty.inzeratyflex` container, `h2.nadpis a` title, `div.inzeratycena` price, `div.inzeratylok` location (city`<br>`postcode), `div.inzeratyview` views
- **Total count**: in `div.listainzerat div.inzeratynadpis`, pattern "z {N}"

## How nehnutelnosti.sk works

- **URL pattern**: `https://www.nehnutelnosti.sk/vysledky/{property_type}/{location}/{transaction}` (order matters!)
- **Pagination**: `?page=N` query param, 30 items/page, starts at 1
- **Data source**: JSON-LD schema.org graph embedded in Next.js RSC `self.__next_f.push()` script chunks
- **Graph path**: `@graph` → `SearchResultsPage` → `mainEntity` (ItemList) → `itemListElement`
- **Per listing**: `name`, `priceSpecification.price`, `floorSize.value` (m²), `url`; no address in JSON-LD (city from URL)
- **Property types**: `byty`, `2-izbove-byty`, `3-izbove-byty`, `domy`, `pozemky`
- **Transaction types**: `predaj`, `prenajom`
- **Flag mapping**: `--subcategory predam/byt` → `/byty/.../predaj`; query "2 izbový" → `/2-izbove-byty/`

## Development

```bash
uv sync            # install deps
uv run b-scrape "2 izbový byt" --category reality --location Michalovce
uv run b-scrape "2 izbový byt" --source nehnutelnosti --subcategory predam/byt --location Michalovce
uv run b-scrape "2 izbový byt" --source all --subcategory predam/byt --location Michalovce
```

## Commands

- `uv sync` — install/update dependencies
- `uv run b-scrape` — run the CLI
