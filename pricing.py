"""
Enrich copart_listings.json with real market prices from Auto.dev and compute max bid.

market_price = median retail listing price for the vehicle's year/make/model
               (Florida listings first, nationwide fallback if < 3 results).
               Listings are mileage-matched to the lot's odometer (+/- 30%)
               when at least 3 comparable-mileage listings exist.
max_bid      = market_price * condition multiplier (non-runner discount)

Usage:  python3 pricing.py
"""
import json, os, sys, csv, time, statistics, urllib.request, urllib.parse, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config

OUT = os.path.dirname(os.path.abspath(__file__))
KEY = config.require("AUTO_DEV_API_KEY")
log = config.get_logger("pricing", "pricing.log")

# ---- condition multipliers (same as scraper) ----
CONDITION_MULTIPLIERS = {
    "CERT-D": 0.45,   # Run & Drive      -> drivable, mechanical issue present
    "CERT-E": 0.35,   # Enhanced         -> inspected, mechanical issue present
    "CERT-S": 0.25,   # Engine Start     -> starts but does NOT drive (non-runner)
    "":       0.20,   # unknown          -> assume non-runner
}
DEFAULT_MULT = 0.20

# ---- mileage matching (Auto.dev market price) ----
# Prefer listings whose odometer is within +/- this fraction of the lot's miles.
MILES_TOLERANCE = 0.30
# If fewer than this many mileage-matched listings, fall back to all listings.
MIN_MATCHES = 3

# ---- Copart -> Auto.dev name mapping ----
MAKE_MAP = {
    "RAM": "Ram", "GMC": "GMC", "BMW": "BMW", "LAND ROVER": "Land Rover",
    "MERCEDES-BENZ": "Mercedes-Benz", "JAGUAR": "Jaguar", "VOLKSWAGEN": "Volkswagen",
    "HYUNDAI": "Hyundai", "CHEVROLET": "Chevrolet", "CADILLAC": "Cadillac",
    "LEXUS": "Lexus", "LINCOLN": "Lincoln", "SUBARU": "Subaru", "BUICK": "Buick",
    "AUDI": "Audi", "FORD": "Ford", "HONDA": "Honda", "JEEP": "Jeep", "KIA": "Kia",
    "MAZDA": "Mazda", "NISSAN": "Nissan", "DODGE": "Dodge", "TOYOTA": "Toyota",
}
MODEL_MAP = {
    "528": "5 Series",
    "735": "7 Series",
    "ML": "M-Class",
    "RANGE ROVER SPORT SC": "Range Rover Sport",
    "F150": "F-150",
    "F250": "F-250",
    "PROMASTER 1500": "ProMaster",
    "PROMASTER 3500": "ProMaster",
    "SILVERADO": "Silverado 1500",
    "I3": "i3",
    "MX-5 MIATA": "MX-5 Miata",
    "NX 200T": "NX 200t",
}

def norm_make(m):
    return MAKE_MAP.get((m or "").upper(), (m or "").title())

def norm_model(m):
    return MODEL_MAP.get((m or "").upper(), (m or "").title())

CACHE_FILE = os.path.join(OUT, "auto_dev_cache.json")
_cache = {}
STATS = {"fresh": 0, "reused": 0}

def _key(make, model, year):
    return "%s||%s||%s" % (make, model, year)

def load_cache():
    global _cache
    _cache = {}
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        # v2 cache format: {key: {"scope": str, "listings": [{price, miles}, ...]}}
        # Old-format entries ({"median": ...}) are ignored and re-queried.
        for k, v in raw.items():
            if isinstance(v, dict) and isinstance(v.get("listings"), list):
                _cache[k] = v
    except Exception:
        _cache = {}

def save_cache():
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f)
    except Exception as e:
        log.warning("cache save failed: %s", e)

def auto_dev_query(make, model, year, state):
    params = {"vehicle.make": make, "vehicle.model": model, "vehicle.year": str(year), "limit": 20}
    if state:
        params["retailListing.state"] = state
    url = "https://api.auto.dev/listings?" + urllib.parse.urlencode(params)
    for attempt in (1, 2):
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + KEY})
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                d = json.load(r)
            listings = d.get("data") or []
            out = []
            for x in listings:
                rl = x.get("retailListing") or {}
                p = rl.get("price")
                if p is None:
                    continue
                try:
                    p = float(p)
                except (TypeError, ValueError):
                    continue
                miles = rl.get("miles")
                try:
                    miles = float(miles) if miles is not None else None
                except (TypeError, ValueError):
                    miles = None
                out.append({"price": p, "miles": miles})
            return out
        except Exception as e:
            if attempt == 2:
                log.warning("auto.dev error %s %s %s: %s", make, model, year, str(e)[:80])
                return None
            time.sleep(1)

def get_market(make, model, year, odo=None):
    k = _key(make, model, year)
    if k in _cache and _cache[k] is not None:
        entry = _cache[k]
        STATS["reused"] += 1
    else:
        entry = None
        for scope in ("FL", None):
            listings = auto_dev_query(make, model, year, scope)
            if listings is None:
                continue
            if len(listings) >= 3:
                entry = {"scope": scope or "US", "listings": listings}
                break
            if entry is None or (listings and len(listings) > len(entry["listings"])):
                entry = {"scope": scope or "US", "listings": listings}
        _cache[k] = entry
        STATS["fresh"] += 1
        time.sleep(0.15)

    if not entry or not entry.get("listings"):
        return None

    listings = entry["listings"]
    n_matched = None
    mileage_adjusted = None
    if odo and odo > 0:
        lo = odo * (1 - MILES_TOLERANCE)
        hi = odo * (1 + MILES_TOLERANCE)
        matched = [l for l in listings if l.get("miles") is not None and lo <= l["miles"] <= hi]
        n_matched = len(matched)
        mileage_adjusted = n_matched >= MIN_MATCHES
        if mileage_adjusted:
            listings = matched

    prices = [l["price"] for l in listings if l.get("price") is not None]
    if not prices:
        return None
    return {
        "median": round(statistics.median(prices)),
        "mean": round(statistics.mean(prices)),
        "n": len(prices),
        "scope": entry["scope"],
        "min": round(min(prices)),
        "max": round(max(prices)),
        "miles_matched": n_matched,
        "mileage_adjusted": mileage_adjusted,
    }

def first_positive(*vals):
    for v in vals:
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if v and v > 0:
            return v
    return None

def main():
    log.info("pricing started")
    load_cache()
    if "refresh" in sys.argv[1:]:
        _cache.clear()
        log.info("cache cleared (refresh flag)")
    rows = json.load(open(os.path.join(OUT, "copart_listings.json"), encoding="utf-8"))
    log.info("enriching %s lots (cache has %s entries)", len(rows), len(_cache))

    n_autodev = n_fallback = 0
    for i, r in enumerate(rows):
        mk = norm_make(r.get("make"))
        md = norm_model(r.get("model"))
        yr = r.get("year")
        try:
            yr = int(yr)
        except (TypeError, ValueError):
            yr = None

        odo = r.get("odometer")
        try:
            odo = float(odo) if odo is not None else None
        except (TypeError, ValueError):
            odo = None

        res = get_market(mk, md, yr, odo) if yr else None
        if res and res.get("median"):
            r["market_price"] = res["median"]
            r["market_avg"] = res["mean"]
            r["market_n_listings"] = res["n"]
            r["market_scope"] = res["scope"]
            r["market_min"] = res["min"]
            r["market_max"] = res["max"]
            r["market_miles_matched"] = res.get("miles_matched")
            r["market_mileage_adjusted"] = res.get("mileage_adjusted")
            r["price_source"] = "auto.dev"
            n_autodev += 1
        else:
            # fallback to Copart's own ACV / est retail / buy-now
            fb = first_positive(r.get("acv"), r.get("est_retail_value"), r.get("buy_now_price"))
            r["market_price"] = fb
            r["market_avg"] = fb
            r["market_n_listings"] = (res or {}).get("n", 0)
            r["market_scope"] = (res or {}).get("scope", "")
            r["market_min"] = (res or {}).get("min")
            r["market_max"] = (res or {}).get("max")
            r["market_miles_matched"] = None
            r["market_mileage_adjusted"] = None
            r["price_source"] = "copart_fallback"
            n_fallback += 1

        # max bid = market_price * condition multiplier
        code = (r.get("condition_code") or "").strip().upper()
        mult = CONDITION_MULTIPLIERS.get(code, DEFAULT_MULT)
        mp = r.get("market_price")
        r["condition_discount_pct"] = round((1 - mult) * 100)
        r["max_bid"] = round(mp * mult) if mp else None

        if (i + 1) % 5 == 0:
            log.info("progress %d/%d", i + 1, len(rows))

    log.info("auto.dev priced: %s | copart fallback: %s", n_autodev, n_fallback)

    # order columns
    order = list(rows[0].keys())
    # write json
    with open(os.path.join(OUT, "copart_listings_priced.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1, default=str)
    # write csv
    with open(os.path.join(OUT, "copart_listings_priced.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=order)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    log.info("saved copart_listings_priced.csv / .json")
    save_cache()
    log.info("api calls this run: %s fresh | %s reused from cache", STATS["fresh"], STATS["reused"])

    # summary
    priced = [r for r in rows if r.get("max_bid")]
    if priced:
        import collections
        log.info("max_bid median: $%s | range $%s - $%s",
                 round(statistics.median(r["max_bid"] for r in priced)),
                 min(r["max_bid"] for r in priced), max(r["max_bid"] for r in priced))
        log.info("price_source: %s", collections.Counter(r["price_source"] for r in rows))
        log.info("market scope: %s", collections.Counter((r.get("market_scope") or "-") for r in rows))
        log.info("mileage-adjusted lots: %d of %d",
                 sum(1 for r in rows if r.get("market_mileage_adjusted")), len(rows))
    log.info("pricing finished")

if __name__ == "__main__":
    main()
