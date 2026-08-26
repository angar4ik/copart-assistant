# Copart Max Bid — Chrome extension (server-backed)

Shows a **suggested max bid** on every Copart lot page, bottom-right corner.
When a lot page opens, it scrapes the vehicle details and POSTs them to your
local server, which stores + prices the car and returns the data to display.

Market pricing only — no bid/live-auction tracking.

## How it works

```
copart.com lot page ──content.js──► background.js ──POST /api/lot──► http://localhost:8000
                                      (service worker)                    │
                                                                          ▼
                                                              server upserts + prices
                                                                          │
                            panel renders the returned record ◄───────────┘
```

The fetch happens in a **background service worker** (extension context), not the
page, so it isn't blocked by the browser's cross-origin / mixed-content rules.

## Prerequisites

1. Start the pricing server: `python3 server.py` (or `python3 start.py` → `[1]`).

## Install (one time)

1. In Chrome, open `chrome://extensions`
2. Turn on **Developer mode** (toggle, top-right)
3. Click **Load unpacked**
4. Select this folder:
   `C:\Users\4anga\Downloads\pi-windows-x64\copart\extension`
5. Open a Copart lot page → panel appears bottom-right.

## Panel

- Vehicle title + lot number
- Condition, odometer, market value (median FL retail), discount %
- **Suggested max bid** (big green number)
- Buy-It-Now (if present)
- ⚠ warnings for missing/mileage-adjusted pricing
- ↻ refresh button, × hide button

## Files

- `manifest.json` — MV3 manifest (host permissions for localhost:8000 + background worker)
- `content.js` — scrapes title / odometer / condition / yard / vin / specs, renders the panel
- `background.js` — service worker that POSTs the lot to the local server

## Notes

- The extension extracts details from page text; if Copart changes its layout,
  update the selectors in `content.js`.
