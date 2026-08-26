# Copart Assistant

A small local tool that shows a **suggested max bid** on Copart lot pages and
builds a searchable history of every vehicle you look at — with **no automated
scraping**. You browse Copart normally; a Chrome extension sends each lot to a
local server, which stores it in SQLite and prices it on demand via Auto.dev.

---

## How it works

```
you browse Copart ──► lot page opens ──► extension scrapes the page
                                              │  POST /api/lot
                                              ▼
                              local server (server.py)
                              ├─ upsert lot + snapshot (SQLite)
                              ├─ if not priced yet: query Auto.dev (cached)
                              └─ return the full record
                                              │
                                              ▼
                              extension shows the max-bid panel
```

For each lot the server keeps:

- **identity** (`lots`) — year / make / model / title, first & last seen
- **history** (`snapshots`) — odometer, condition, yard per visit
- **valuation** (`pricings`) — market price, max bid, mileage flags per pricing run
- **Auto.dev comps** (`market_cache`) — cached per make/model/year

Everything lives in one SQLite file, `copart.db`.

---

## Quick start

1. Start the server: `python3 start.py` → `[1] Run pricing server`
   (or directly `python3 server.py`).
2. Load the extension (see below).
3. Browse Copart and open any lot page — the panel appears bottom-right, and the
   server prices the car automatically on first sight.

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

Condition multipliers (`pricing.py`):

| Copart condition | Meaning | Multiplier |
|---|---|---|
| `CERT-D` | Run & Drive | 0.45 |
| `CERT-E` | Enhanced (mechanical issue) | 0.35 |
| `CERT-S` | Engine Start (does not drive) | 0.25 |
| *(unknown)* | assume non-runner | 0.20 |

Tunables in `pricing.py`: `MILES_TOLERANCE = 0.30`, `MIN_MATCHES = 3`,
`CONDITION_MULTIPLIERS`.

The condition code is mapped from the lot page's label ("Run & Drive" →
`CERT-D`, "Enhanced Vehicles" → `CERT-E`, "Engine Start" → `CERT-S`), and
year/make/model are parsed from the lot title. Pricing is computed **once per
car** and stored; re-visits reuse the stored valuation.

```bash
python3 pricing.py                # re-price every lot in the DB
python3 pricing.py refresh        # clear the Auto.dev cache, then re-price
python3 pricing.py --clear-cache  # clear the cache only
```

---

## Configuration (`.env`)

Copy `.env.example` to `.env` and fill in your values. `.env` is gitignored.

```bash
AUTO_DEV_API_KEY=sk_...          # free key at https://www.auto.dev
```

`COPART_EMAIL` / `COPART_PASSWORD` / `HEADLESS` are **no longer needed** — there
is no automated login or scraping anymore.

---

## Chrome extension

Loads on `https://www.copart.com/lot/*` and shows a panel (bottom-right) with:

- Vehicle title + lot number
- Condition, odometer, market value, discount %
- **Suggested max bid** (big green number)
- Buy-It-Now (if present)
- Warnings:
  - ⚠ no Auto.dev price (using Copart estimate)
  - ⚠ high mileage — no comparable comps
  - ⚠ no odometer data — price not mileage-adjusted

### Install (one time)

1. Chrome → `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select the `extension/` folder
4. Start the pricing server and open a lot page

### Update after code changes

Click the ↻ reload icon on the extension in `chrome://extensions`, then reload the lot page.

---

## Database

All data lives in a single SQLite file, `copart.db` (gitignored).

| Table | Purpose |
|---|---|
| `lots` | One row per vehicle (stable identity + attributes) |
| `snapshots` | One row per lot per visit — builds history over time |
| `pricings` | One row per lot per pricing run — `market_price`, `max_bid`, mileage flags |
| `market_cache` | Auto.dev API cache (comps per make/model/year) |

Query it directly with `sqlite3 copart.db` or any SQLite GUI.

---

## Logging

Every script writes timestamped logs to `logs/` (rotating, 2 MB × 3 backups):

- `logs/pricing.log`
- `logs/menu.log`
- `logs/server.log`

---

## Project layout

```
copart/
├── start.py / start.bat      # menu (run server, re-price, clear cache)
├── server.py                 # local HTTP server (POST /api/lot)
├── pricing.py                # Auto.dev pricing + title parsing + cache
├── db.py                     # SQLite schema + all read/write helpers
├── config.py                 # .env loader + logger helper
├── copart.db                 # SQLite database (source of truth, gitignored)
├── .env / .env.example       # secrets (gitignored) / template
├── extension/
│   ├── manifest.json         # MV3 manifest
│   ├── content.js            # scrapes lot page, renders panel
│   ├── background.js         # POSTs to the local server (extension context)
│   └── README.md
└── logs/                     # rotating logs
```

---

## Requirements

- Python 3 (use `python3`)
- A free Auto.dev API key
- Chrome (for the extension)

## Notes & caveats

- Pricing is computed once per car on first sight; it is **not** re-fetched on
  every visit (Auto.dev data is cached per make/model/year). Use
  `pricing.py refresh` to force a full re-price.
- The extension extracts lot details from the page text (title, odometer,
  condition, yard). If Copart changes its page layout, those fields may
  need selector updates in `extension/content.js`.
- The mileage-matched median can still overvalue very high-mileage lots when
  fewer than 3 comparable listings exist — the panel flags these with an amber
  warning.
