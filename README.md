# Copart Assistant

A toolkit for finding, pricing, and tracking **Copart** auction vehicles — focused on
**Florida (Ocala + Orlando North + Orlando South), Clean Title, Mechanical-damage**
vehicles — plus a Chrome extension that shows a live **max-bid** suggestion and records
bid activity as auctions progress.

---

## What it does

| Step | Tool | Output |
|---|---|---|
| 1. Scrape Copart | `copart_scrape.py` | `copart_listings.json` / `.csv`, appends `history.csv` |
| 2. Price from market | `pricing.py` | `copart_listings_priced.json` / `.csv` |
| 3. Serve data locally | `server.py` | `http://localhost:8000` |
| 4. Browse + track bids | Chrome extension (`extension/`) | panel on lot pages, records to `live_bids.json` |

Everything is driven by an interactive menu (`start.py` / `start.bat`).

---

## Quick start

```bash
python3 start.py        # or double-click start.bat
```

Menu:

```
  [1] Scrape Copart
  [2] Grab pricing (Auto.dev)
  [3] Scrape + pricing (both)
  [4] Run pricing server   (http://localhost:8000)
  [5] Exit
```

Recommended first run:

1. `[1]` Scrape Copart (headless Chrome, no window)
2. `[2]` Grab pricing (Auto.dev market values)
3. `[4]` Run pricing server (for the Chrome extension)

---

## Configuration (`.env`)

Copy `.env.example` to `.env` and fill in your values. `.env` is gitignored.

```bash
COPART_EMAIL=you@example.com
COPART_PASSWORD=your-password
AUTO_DEV_API_KEY=sk_...          # free key at https://www.auto.dev
HEADLESS=true                    # true = no Chrome window; false = visible browser
```

- `COPART_EMAIL` / `COPART_PASSWORD` — your Copart member sign-in.
- `AUTO_DEV_API_KEY` — Auto.dev API key (free tier: 1,000 calls/month).
- `HEADLESS` — run the scraper's browser in windowless mode (`true` by default).

---

## Pricing methodology

For each lot:

```
market_price = median retail listing price for the vehicle's year/make/model
               (Florida listings first, nationwide fallback if < 3 results)
               -> mileage-matched to the lot's odometer within +/- 30%,
                  when at least 3 comparable-mileage listings exist

max_bid = market_price × condition multiplier
```

Condition multipliers (in `copart_scrape.py` and `pricing.py`):

| Copart condition | Meaning | Multiplier |
|---|---|---|
| `CERT-D` | Run & Drive | 0.45 |
| `CERT-E` | Enhanced (mechanical issue) | 0.35 |
| `CERT-S` | Engine Start (does not drive) | 0.25 |
| *(unknown)* | assume non-runner | 0.20 |

Tunables in `pricing.py`:

- `MILES_TOLERANCE = 0.30` — odometer match window (±30%).
- `MIN_MATCHES = 3` — min comparable-mileage listings before using them.
- `CONDITION_MULTIPLIERS` — the discount per condition tier.

The Auto.dev results are cached in `auto_dev_cache.json` (keyed by `make|model|year`)
so re-runs only query the API for new models.

```bash
python3 pricing.py          # reuse cache, only price new lots
python3 pricing.py refresh  # force re-fetch everything
```

---

## Chrome extension

Loads on `https://www.copart.com/lot/*` and shows a panel (bottom-right) with:

- Vehicle title + lot number
- Condition, odometer, market value, discount %
- **Suggested max bid** (big green number)
- Buy-It-Now / current bid
- Warnings:
  - ⚠ current bid already above your max
  - ⚠ no Auto.dev price (using Copart estimate)
  - ⚠ high mileage — no comparable comps
  - ⚠ window too narrow (see note below)

### Install (one time)

1. Chrome → `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select the `extension/` folder
4. Start the pricing server (menu `[4]`) and open a lot page

### Update after code changes

Click the ↻ reload icon on the extension in `chrome://extensions`, then reload the lot page.

> **Copart bug:** the current bid is not rendered when the viewport is narrower than
> **1025 px**. Keep the Chrome window ≥1025 px wide so the panel can read the live bid.

---

## Live bid collection

While a lot page is open, the extension scrapes and POSTs the following to the server,
which appends each record to `live_bids.json`:

```json
{
  "lot_number": "65845396",
  "title": "2020 HYUNDAI ELANTRA SEL",
  "year": 2020, "make": "HYUNDAI", "model": "ELANTRA",
  "odometer": 178561,
  "current_bid": 375,
  "countdown": "0D 1H 45min",
  "sale_status": "On approval",
  "max_bid": 4424, "market_price": 12640,
  "condition_code": "CERT-E", "yard": "FL - ORLANDO NORTH",
  "client_time": "...", "server_time": "..."
}
```

- Sent immediately when the page loads, and re-sent **the moment the bid or sale
  status changes** (via a `MutationObserver`, ~300 ms debounce).
- Deduped by `bid + sale_status` — countdown ticking alone does not spam records.
- A 60 s safety-net poll catches anything the observer misses.

---

## Data files

| File | Purpose |
|---|---|
| `copart_listings.json` / `.csv` | Raw scrape output (current filtered lots) |
| `copart_listings_priced.json` / `.csv` | Final output with `market_price`, `max_bid`, mileage flags |
| `history.csv` | Append-only snapshot history (one dated row-set per scrape) |
| `auto_dev_cache.json` | Auto.dev API cache |
| `live_bids.json` | Collected live bid records from the extension |

All of the above are gitignored (generated data).

---

## Logging

Every script writes timestamped logs to `logs/` (rotating, 2 MB × 3 backups):

- `logs/scrape.log`
- `logs/pricing.log`
- `logs/menu.log`
- `logs/server.log`

---

## Project layout

```
copart/
├── start.py / start.bat      # interactive menu
├── copart_scrape.py          # Copart scraper (headless browser + search API)
├── pricing.py                # Auto.dev pricing + mileage matching + cache
├── server.py                 # local HTTP server (static + POST /api/bid)
├── config.py                 # .env loader + logger helper
├── .env / .env.example       # secrets (gitignored) / template
├── extension/
│   ├── manifest.json         # MV3 manifest
│   ├── content.js            # panel, scraping, MutationObserver
│   ├── background.js         # fetch pricing + POST bids (extension context)
│   └── README.md
├── logs/                     # rotating logs
└── (generated data files)
```

---

## Requirements

- Python 3 (use `python3`)
- Real Google Chrome (for the scraper's stealth browser)
- A Copart account (free/Guest tier works, but full VINs are masked)
- A free Auto.dev API key

## Notes & caveats

- Copart only exposes **current/upcoming** lots via search; sold lots are not
  retroactively queryable. `history.csv` + `live_bids.json` build that history over time.
- Guest-tier Copart accounts mask the last 6 VIN digits.
- The mileage-matched median can still overvalue very high-mileage lots when fewer
  than 3 comparable listings exist — the plugin flags these with an amber warning.
