"""
Auto.dev market pricing for a single lot (called on demand by the server).

market_price = median retail listing price for the vehicle's year/make/model
               (Florida listings first, nationwide fallback if < 3 results).
               Listings are mileage-matched to the lot's odometer (+/- 30%)
               when at least 3 comparable-mileage listings exist.
max_bid      = market_price * condition multiplier (non-runner discount)

Usage (optional CLI):
  python3 pricing.py                # re-price every lot in the DB
  python3 pricing.py refresh        # clear the Auto.dev cache, then re-price
  python3 pricing.py --clear-cache  # clear the cache only
"""
import sys
import json
import re
import time
import statistics
import urllib.request
import urllib.parse
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config
import db

log = config.get_logger("pricing", "pricing.log")

# ---- condition multipliers ----
CONDITION_MULTIPLIERS = {
    "CERT-D": 0.45,   # Run & Drive      -> drivable, mechanical issue present
    "CERT-E": 0.35,   # Enhanced         -> inspected, mechanical issue present
    "CERT-S": 0.25,   # Engine Start     -> starts but does NOT drive (non-runner)
    "":       0.20,   # unknown          -> assume non-runner
}
DEFAULT_MULT = 0.20

# ---- mileage matching (Auto.dev market price) ----
MILES_TOLERANCE = 0.30
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

# Makes we can recognize in a Copart title (uppercase), longest first.
MAKES = sorted(set(list(MAKE_MAP.keys()) + [
    "MERCEDES-BENZ", "LAND ROVER", "ASTON MARTIN", "ALFA ROMEO", "ROLLS-ROYCE",
    "ACURA", "CHRYSLER", "INFINITI", "MITSUBISHI", "VOLVO", "PORSCHE", "TESLA",
    "FIAT", "MINI", "SCION", "PONTIAC", "SATURN", "SUZUKI", "ISUZU", "MERCURY",
    "OLDSMOBILE", "PLYMOUTH", "HUMMER", "SAAB", "SMART", "GENESIS", "MASERATI",
    "BENTLEY", "FERRARI", "LAMBORGHINI",
]), key=len, reverse=True)


def norm_make(m):
    return MAKE_MAP.get((m or "").upper(), (m or "").title())


def norm_model(m):
    return MODEL_MAP.get((m or "").upper(), (m or "").title())


def _candidate_models(raw_model):
    """Try progressively shorter model strings so a trim suffix (e.g. 'ELANTRA SEL')
    still falls back to the base model ('Elantra'). Each is mapped via norm_model."""
    words = (raw_model or "").split()
    out = []
    seen = set()
    for i in range(len(words), 0, -1):
        m = norm_model(" ".join(words[:i]))
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def parse_title(title):
    """Return (year, make, model) from a Copart title like '2020 HYUNDAI ELANTRA SEL'.
    make/model are Copart-style uppercase; norm_make/norm_model map them to Auto.dev."""
    title = (title or "").strip()
    m = re.search(r"\b(19|20)\d{2}\b", title)
    year = int(m.group(0)) if m else None
    rest = title.upper()
    if m:
        rest = (title[:m.start()] + " " + title[m.end():]).upper()
    rest = re.sub(r"\s+", " ", rest).strip()
    make = None
    for mk in MAKES:
        if rest == mk or rest.startswith(mk + " "):
            make = mk
            break
    model = rest[len(make) + 1:].strip() if make else rest
    return year, make, model


def map_condition(text):
    """Map a Copart condition label (from the lot page) to a CERT code."""
    t = (text or "").upper()
    if "RUN" in t and "DRIVE" in t:
        return "CERT-D"
    if "ENHANCED" in t:
        return "CERT-E"
    if "ENGINE START" in t or "START PROGRAM" in t or "STARTS" in t:
        return "CERT-S"
    return ""


KEY = config.require("AUTO_DEV_API_KEY")

# in-run mirror of the DB cache (avoids re-reading SQLite per lot)
_cache = {}
STATS = {"fresh": 0, "reused": 0}


def _key(make, model, year):
    return "%s||%s||%s" % (make, model, year)


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
    entry = _cache.get(k)
    hit = k in _cache and entry is not None
    if not hit:
        entry = db.cache_get(make, model, year)
        if entry is not None:
            _cache[k] = entry
            hit = True

    if hit:
        STATS["reused"] += 1
        if entry and entry.get("listings"):
            odo_s = ("%s mi" % format(int(odo), ",")) if odo else "—"
            log.info("pricing cache hit: %s %s %s (%s, %s comps)",
                     year, make, model, odo_s, len(entry["listings"]))
    else:
        log.info("NEW pricing search: %s %s %s", year, make, model)
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
        if entry is not None:
            db.cache_put(make, model, year, entry["scope"], entry["listings"])
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


def price_lot(lot):
    """Compute pricing fields for one lot dict. Returns a pricing row (or None)."""
    lot_number = lot.get("lot_number")
    if not lot_number:
        return None

    mk = norm_make(lot.get("make"))
    raw_model = lot.get("model") or ""
    yr = lot.get("year")
    try:
        yr = int(yr)
    except (TypeError, ValueError):
        yr = None

    odo = lot.get("odometer")
    try:
        odo = float(odo) if odo is not None else None
    except (TypeError, ValueError):
        odo = None

    res = None
    if yr and mk:
        for cm in _candidate_models(raw_model):
            res = get_market(mk, cm, yr, odo)
            if res and res.get("median"):
                break

    code = (lot.get("condition_code") or "").strip().upper()
    mult = CONDITION_MULTIPLIERS.get(code, DEFAULT_MULT)

    pr = {
        "lot_number": lot_number,
        "condition_code": code,
        "condition_discount_pct": round((1 - mult) * 100),
    }
    if res and res.get("median"):
        pr["price_source"] = "auto.dev"
        pr["market_price"] = res["median"]
        pr["market_avg"] = res["mean"]
        pr["market_n_listings"] = res["n"]
        pr["market_scope"] = res["scope"]
        pr["market_min"] = res["min"]
        pr["market_max"] = res["max"]
        pr["market_miles_matched"] = res.get("miles_matched")
        pr["market_mileage_adjusted"] = 1 if res.get("mileage_adjusted") else 0
    else:
        fb = first_positive(lot.get("acv"), lot.get("est_retail_value"), lot.get("buy_now_price"))
        pr["price_source"] = "copart_fallback"
        pr["market_price"] = fb
        pr["market_avg"] = fb
        pr["market_n_listings"] = (res or {}).get("n", 0)
        pr["market_scope"] = (res or {}).get("scope", "")
        pr["market_min"] = (res or {}).get("min")
        pr["market_max"] = (res or {}).get("max")
        pr["market_miles_matched"] = None
        pr["market_mileage_adjusted"] = None

    pr["max_bid"] = round(pr["market_price"] * mult) if pr["market_price"] else None
    return pr


def main():
    db.init_db()
    if "--clear-cache" in sys.argv[1:]:
        db.cache_clear()
        log.info("Auto.dev cache cleared")
        print("Auto.dev cache cleared.")
        return
    if "refresh" in sys.argv[1:]:
        db.cache_clear()
        log.info("cache cleared (refresh flag)")

    rows = db.all_lots()
    log.info("re-pricing %s lots", len(rows))
    run_id = db.now()
    pricings = [p for p in (price_lot(r) for r in rows) if p]
    db.save_pricings(pricings, run_id)
    priced = [p for p in pricings if p.get("max_bid")]
    log.info("saved %s pricings (%s with max bid)", len(pricings), len(priced))
    print("Re-priced %s lots (%s with max bid)." % (len(pricings), len(priced)))


if __name__ == "__main__":
    main()
