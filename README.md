# flatview

Market-tracking CLI for Slovak and Czech real-estate classified ads. Aggregates listings from [bazos.sk](https://www.bazos.sk)/[bazos.cz](https://www.bazos.cz), [nehnutelnosti.sk](https://www.nehnutelnosti.sk), and [topreality.sk](https://www.topreality.sk) with price analysis, saved-search tracking, and email digests.

## Features

- Search across **bazos.sk**, **bazos.cz**, **nehnutelnosti.sk**, and **topreality.sk** — individually or combined
- **Price insights**: percentiles (P10–P90), average, min/max for both price and €/m²
- **Two-sided outlier detection**: IQR fence on €/m² flags potential **bargains** (↓) and **overpriced** ads (↑)
- **Segmentation**: new build vs resale classification from listing text
- **Watches + tracking**: save a search, run `flatview track` on a schedule, get notified about new listings, price drops, and delistings
- **Email digest**: HTML digest written locally on every run and optionally sent via SMTP
- **Floor area extraction**: from JSON-LD (nehnutelnosti), HTML (topreality), and bazos detail pages
- **Duplicate detection**: fuzzy matching highlights listings that appear on multiple portals
- **Export**: CSV, XLSX, PDF, and interactive HTML report (Plotly charts, CMA mode)
- **SQLite history**: every observed listing and price change is stored for trend analysis

## Installation

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/lst-v/flatview.git
cd flatview
uv sync
```

## Usage

### One-shot search

```bash
# Search bazos.sk (default source); bare form implies the `search` subcommand
uv run flatview "2 izbový byt" --subcategory predam/byt --location Michalovce

# All portals combined, full pagination, HTML report
uv run flatview search "2 izbový byt" --source all --subcategory predam/byt \
  --location Michalovce --pages 0 --export html

# Comparative market analysis for a 55 m² flat
uv run flatview search "2 izbový byt" --source all --subcategory predam/byt \
  --location Michalovce --export html --report cma --cma-area 55

# Czech bazos
uv run flatview "2+kk" --site bazos.cz --subcategory prodam/byt --location Praha
```

### Tracking & notifications

Save a search as a named watch, then run `track` repeatedly (manually or scheduled):

```bash
uv run flatview watch add mi-2izb "2 izbový byt" --source all \
  --subcategory predam/byt --location Michalovce
uv run flatview watch list
uv run flatview track            # runs every active watch
uv run flatview track --dry-run  # scrape + detect events, write nothing
uv run flatview watch remove mi-2izb
```

Each `track` run detects, per watch:

- **New listings** — first seen by this watch (the very first run is a baseline and does not flood you)
- **Price drops / increases** — vs the last stored price
- **Delistings** — listings not seen for 2+ days (configurable); likely sold or withdrawn
- **Bargains / overpriced** — two-sided IQR outliers on €/m²
- **Market trend** — median €/m² and active-listing count vs 7 days ago, a 30-day median series, median days on market of recent delistings, and price-cut share/size — all computed from the stored history, cross-posts counted once

Every run writes an HTML digest to `~/.local/share/flatview/digests/` (plus `latest.html`). With SMTP configured, the digest is also emailed — by default only when something actually happened. With `[ntfy]` configured, event runs additionally send a push notification to your phone.

### Push notifications (ntfy)

[ntfy](https://ntfy.sh) is a free pub-sub push service: install the ntfy app (iOS/Android), subscribe to a topic of your choosing, and flatview publishes to it. Pick a long random topic name — the topic *is* the secret on the public ntfy.sh server.

```toml
[ntfy]
topic = "flatview-mysecret-x7q2k9"
# server = "https://ntfy.sh"   # or your self-hosted instance
# token: use the FLATVIEW_NTFY_TOKEN env var for protected topics
```

Pushes are sent only when something happened (new/drops/delisted/failures) — quiet runs stay quiet. `--no-push` skips the push for one run.

### Email configuration

Create `~/.config/flatview/config.toml`:

```toml
[smtp]
host = "smtp.gmail.com"
port = 587
username = "me@gmail.com"
from = "me@gmail.com"
to = ["me@gmail.com"]
# password: prefer the FLATVIEW_SMTP_PASSWORD env var over storing it here

[tracking]
delist_after_days = 2          # grace window before a missing listing counts as delisted
email_only_on_events = true    # false = email every run, even with no changes
backup_keep = 7                # daily DB backups kept in ~/.local/share/flatview/backups (0 = off)
# healthcheck_url = "https://hc-ping.com/<uuid>"   # pinged after each run (/fail on failure)

[analytics]
iqr_k = 1.5                    # outlier fence multiplier; lower flags more bargains/overpriced
cma_area_band = 0.25           # CMA comparables within ±25% of the target area
```

The `[analytics]` section applies to `search` (console, exports, HTML/CMA report) and `track` (digest outliers) alike.

For Gmail use an [app password](https://myaccount.google.com/apppasswords). Without an `[smtp]` section, `track` is local-only (digest file, no email) — never an error.

### Scheduling on macOS

**launchd (recommended)** — runs missed jobs after sleep and avoids cron's Full Disk Access friction. Create `~/Library/LaunchAgents/sk.flatview.track.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>sk.flatview.track</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/uv</string>
    <string>run</string>
    <string>--project</string>
    <string>/Users/YOU/IdeaProjects/flatview</string>
    <string>flatview</string>
    <string>track</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>30</integer></dict>
  <key>EnvironmentVariables</key>
  <dict><key>FLATVIEW_SMTP_PASSWORD</key><string>app-password-here</string></dict>
  <key>StandardOutPath</key><string>/Users/YOU/.local/state/flatview/track.out.log</string>
  <key>StandardErrorPath</key><string>/Users/YOU/.local/state/flatview/track.err.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/sk.flatview.track.plist
launchctl start sk.flatview.track   # test it now
```

**crontab alternative:**

```cron
30 7 * * * cd ~/IdeaProjects/flatview && FLATVIEW_SMTP_PASSWORD=... /opt/homebrew/bin/uv run flatview track >> ~/.local/state/flatview/cron.log 2>&1
```

`track` exits 0 when all watches succeed, 1 when any watch fails (network down, portal unreachable), 2 on usage/config errors. A failed run never mutates tracking state, so a flaky network cannot cause false delistings.

**Ops safety nets**: each non-dry run snapshots the DB first (daily, rotated per `backup_keep`, via the SQLite backup API). With `healthcheck_url` set (e.g. a free [healthchecks.io](https://healthchecks.io) check), every run pings it — success or `/fail` — so you get alerted when the schedule silently stops firing, not just when a scrape fails.

## CLI options

Subcommands: `search` (default), `watch add|list|remove`, `track`. Search flags (shared by `search` and `watch add`):

| Flag | Default | Description |
|------|---------|-------------|
| `query` | | Search query (positional) |
| `--source` | `bazos` | `bazos`, `nehnutelnosti`, `topreality`, or `all` |
| `--category` | `reality` | Bazos category subdomain |
| `--subcategory` | | Path like `predam/byt`, `prenajmu/dom` |
| `--location` | | City name |
| `--radius` | `25` | Search radius in km (bazos only) |
| `--strict-location` | off | Exact city name match |
| `--zip` | | Postcode filter (bazos only) |
| `--price-from` / `--price-to` | | Price range |
| `--site` | `bazos.sk` | `bazos.sk` or `bazos.cz` |
| `--filter` | | Regex filter on titles |
| `--pages` | `1` | Pages to scrape (`0` = all; watches default to all) |

`search`-only: `--export csv,xlsx,pdf,html`, `--output-dir`, `--report full|cma`, `--cma-area`, `--cma-segment new|resale`, `--remove-outliers`, `--no-store`, `--db-path`. `track`-only: `--watch NAME`, `--dry-run`, `--no-email`, `--no-push`, `--config`. All subcommands accept `-v` for debug logging (file log at `~/.local/state/flatview/flatview.log`).

## How it works

**bazos.sk/cz**: Scrapes HTML listing cards from search results. Fetches each listing's detail page to extract floor area (m²) from the description. Supports subdomain-based categories (`reality.bazos.sk`, `auto.bazos.sk`, etc.).

**nehnutelnosti.sk**: Extracts structured JSON-LD data from Next.js server-rendered pages. Floor area and price are available directly in the search results.

**topreality.sk**: Parses server-rendered HTML cards; resolves locations to district IDs via the site's AJAX endpoint.

**Combined mode** (`--source all`): Runs all scrapers, displays results grouped by source, then shows combined price statistics. Cross-source duplicates are detected via fuzzy title matching and highlighted with `*`.

**Tracking**: watches, per-watch listing membership, and run history live in SQLite (`~/.local/share/flatview/flatview.db`). New/delisted detection is per watch, so overlapping watches don't interfere. All HTTP requests go through a shared client with 1 s rate limiting and exponential-backoff retries.

## License

[MIT](LICENSE)
