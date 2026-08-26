# Copart Max Bid — Chrome extension (server-backed)

Shows a **suggested max bid** on every Copart lot page, bottom-right corner.
Reads pricing **live from your local server** — no re-packing needed when data changes.

## How it works

```
copart.com lot page ──content.js──► background.js ──fetch──► http://localhost:8000/copart_listings_priced.json
```

The fetch happens in a **background service worker** (extension context), not the page,
so it isn't blocked by the browser's cross-origin / mixed-content rules.

## Prerequisites

1. Start the pricing server: menu `[4] Run pricing server`, or `python3 server.py`.
   It serves `copart_listings_priced.json` at `http://localhost:8000`.

## Install (one time)

1. In Chrome, open `chrome://extensions`
2. Turn on **Developer mode** (toggle, top-right)
3. Click **Load unpacked**
4. Select this folder:
   `C:\Users\4anga\Downloads\pi-windows-x64\copart\extension`
5. Open a Copart lot page → panel appears bottom-right.

## Update pricing

```
python3 start.py     # menu: scrape + pricing
```

Then reload the lot page (or click the ↻ refresh button in the panel).
No need to reload the extension.

## Panel

- Vehicle title + lot number
- Condition, market value (median FL retail), discount %
- **Suggested max bid** (big green number)
- Buy-It-Now / current bid (if present)
- ⚠ warning if the current bid exceeds your max
- ↻ refresh button, × hide button

## Files

- `manifest.json` — MV3 manifest (host permissions for localhost:8000 + background worker)
- `content.js` — reads lot # from URL, renders the panel, asks background for data
- `background.js` — service worker that fetches the JSON from the local server
