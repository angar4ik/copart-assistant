"""
Copart filtered-lot scraper + max-bid pricing.

What it does:
  - Reuses a persistent Chrome profile (auto re-logs in if needed).
  - Queries Copart's internal search API: POST /public/lots/search-results
  - Exports a clean CSV + JSON of the current filtered listings.
  - Appends a dated snapshot to history.csv (re-run daily to build a price history).
  - Computes a max bid for each vehicle:
        market_value = est. retail value, else ACV, else Buy-It-Now
        max_bid      = market_value * condition multiplier
    where the multiplier discounts for non-runner / not-best condition.

Usage:  python3 copart_scrape.py
"""
import asyncio, sys, os, json, csv, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\4anga\.pi\agent\skills\stealth-browser\scripts")
from browser import CHROME_PATH
import nodriver as uc
import config

OUT = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(OUT, "profile")
EMAIL = config.require("COPART_EMAIL")
PASS = config.require("COPART_PASSWORD")
HEADLESS = config.get_bool("HEADLESS", True)
log = config.get_logger("scrape", "scrape.log")

# --- Your filter: FL, Ocala + Orlando North + Orlando South, Mechanical damage, Clean Title ---
FILTER = {
    "PRID": ["damage_type_code:DAMAGECODE_MC"],           # primary damage = Mechanical
    "MISC": ["#LocState:\"FL\""],                          # state = Florida
    "LOC": [
        "yard_name:\"FL - OCALA\"",
        "yard_name:\"FL - ORLANDO NORTH\"",
        "yard_name:\"FL - ORLANDO SOUTH\"",
    ],
    "TITL": ["title_group_code:TITLEGROUP_C"],             # title group = Clean Title
}

# =====================================================================
# PRICING MODEL (edit these to change your max-bid logic)
# =====================================================================
# Max bid = market_value * condition multiplier.
# The multiplier is how much of market value you're willing to pay,
# already discounting for mechanical / non-runner / poor condition.
CONDITION_MULTIPLIERS = {
    "CERT-D": 0.45,   # Run & Drive      -> drivable, mechanical issue present
    "CERT-E": 0.35,   # Enhanced         -> inspected, mechanical issue present
    "CERT-S": 0.25,   # Engine Start     -> starts but does NOT drive (non-runner)
    "":       0.20,   # unknown          -> assume non-runner (most conservative)
}
DEFAULT_MULT = 0.20

def first_positive(*vals):
    for v in vals:
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if v and v > 0:
            return v
    return None

def price_lot(r):
    """Return dict with market_value, value_anchor, discount_pct, max_bid."""
    est = r.get("est_retail_value")
    acv = r.get("acv")
    bnp = r.get("buy_now_price")
    if est and float(est) > 0:
        mv, anchor = float(est), "retail"
    elif acv and float(acv) > 0:
        mv, anchor = float(acv), "acv"
    elif bnp and float(bnp) > 0:
        mv, anchor = float(bnp), "buy_now"
    else:
        mv, anchor = None, None

    code = (r.get("condition_code") or "").strip().upper()
    mult = CONDITION_MULTIPLIERS.get(code, DEFAULT_MULT)
    max_bid = round(mv * mult) if mv else None
    disc = round((1 - mult) * 100)
    return {
        "value_anchor": anchor,
        "market_value": mv,
        "condition_discount_pct": disc,
        "max_bid": max_bid,
    }

# =====================================================================

def build_body(page=0, size=200):
    return {
        "query": ["*"],
        "filter": FILTER,
        "sort": ["auction_date_utc asc", "lot_number asc"],
        "page": page, "size": size, "start": 0,
        "watchListOnly": False, "freeFormSearch": False, "hideImages": False,
        "defaultSort": False, "vanityKeyword": False, "specificRowProvided": False,
        "displayName": "", "searchName": "", "backUrl": "", "includeTagByField": {},
        "rawParams": {}
    }

async def js(tab, s):
    return await tab.evaluate(s)

async def fetch_in_page(tab, url, body_json):
    await js(tab, "window.__fr=null; window.__fe=null;")
    code = ("(async()=>{try{const r=await fetch(%s,{method:'POST',headers:{'Content-Type':'application/json'},"
            "body:%s,credentials:'include'});window.__fr={s:r.status,t:await r.text()};}catch(e){window.__fe=String(e);}})()") \
            % (json.dumps(url), json.dumps(body_json))
    await js(tab, code)
    for _ in range(40):
        await asyncio.sleep(0.5)
        r = await js(tab, "JSON.stringify(window.__fr||null)")
        if r and r != "null":
            return json.loads(r)
        if await js(tab, "window.__fe"):
            raise RuntimeError("fetch error")
    raise TimeoutError("fetch timeout")

async def ensure_login(browser, tab):
    await tab.get("https://www.copart.com/dashboard")
    await tab.wait(8)
    url = await js(tab, "document.location.href")
    body = await js(tab, "document.body.innerText.slice(0,2000)")
    if "dashboard" in url and "Sign in" not in (body or ""):
        log.info("already logged in")
        return True
    log.info("logging in to Copart...")
    await tab.get("https://www.copart.com/login")
    await tab.wait(6)
    await js(tab, "(function(){var b=document.getElementById('onetrust-accept-btn-handler');if(b)b.click();return 1;})()")
    await tab.wait(2)
    await js(tab, """
        (function(){
            function setNative(el,v){ if(!el)return false;
                var s=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el),'value').set;
                if(s)s.call(el,v); else el.value=v;
                el.dispatchEvent(new Event('input',{bubbles:true}));
                el.dispatchEvent(new Event('change',{bubbles:true})); return true; }
            var a=setNative(document.getElementById('email-member-number'), %s);
            var b=setNative(document.getElementById('member-password'), %s);
            return JSON.stringify({a:a,b:b});
        })()
    """ % (json.dumps(EMAIL), json.dumps(PASS)))
    await tab.wait(2)
    await js(tab, "(function(){var b=document.querySelector('button.sign-in-button');if(b){b.click();return true;}return false;})()")
    await tab.wait(10)
    return True

def ms_to_date(ms, tz=""):
    if not ms:
        return ""
    try:
        return datetime.datetime.fromtimestamp(ms/1000).strftime("%Y-%m-%d")
    except Exception:
        return ""

def clean_lot(c):
    dd = c.get("dynamicLotDetails") or {}
    return {
        "lot_number": c.get("ln"),
        "year": c.get("lcy"),
        "make": c.get("mkn"),
        "model": c.get("lm"),
        "trim": c.get("ltd"),
        "title": c.get("ld"),
        "body_style": c.get("bstl"),
        "color": c.get("clr"),
        "engine": c.get("egn"),
        "cylinders": c.get("cy"),
        "transmission": c.get("tmtp"),
        "drivetrain": c.get("drv"),
        "fuel": c.get("ft"),
        "odometer": c.get("orr"),
        "odometer_brand": c.get("ord"),
        "keys": c.get("hk"),
        "drive_status": c.get("driveStatus"),
        "title_group": c.get("tgd"),
        "title_code": c.get("stt"),
        "title_desc": c.get("td"),
        "primary_damage": c.get("dd"),
        "secondary_damage": c.get("sdd"),
        "lot_condition": c.get("lcd"),
        "condition_code": c.get("lcc"),
        "yard": c.get("yn"),
        "sale_status": c.get("ess"),
        "sale_status_code": dd.get("saleStatus"),
        "lot_sold": dd.get("lotSold"),
        "current_bid": c.get("hb"),
        "buy_now_price": c.get("bnp"),
        "est_retail_value": (None if (c.get("la") in (None, -1.0, -1)) else c.get("la")),
        "acv": c.get("lotPlugAcv"),
        "repair_cost": c.get("rc"),
        "sale_date": ms_to_date(c.get("ad")),
        "sale_time": c.get("at"),
        "timezone": c.get("tz"),
        "item_number": c.get("aan"),
        "seller": c.get("scn"),
        "vin": c.get("fv"),
        "lot_url": ("https://www.copart.com/lot/%s/%s" % (c.get("ln"), c.get("ldu") or "")) if c.get("ln") else "",
        "image": c.get("tims"),
    }

FIELDS = ["lot_number","year","make","model","trim","title","body_style","color","engine","cylinders",
          "transmission","drivetrain","fuel","odometer","odometer_brand","keys","drive_status",
          "title_group","title_code","title_desc","primary_damage","secondary_damage","lot_condition",
          "condition_code","yard","sale_status","sale_status_code","lot_sold","current_bid",
          "buy_now_price","est_retail_value","acv","repair_cost","sale_date","sale_time","timezone",
          "item_number","seller","vin","lot_url","image",
          "value_anchor","market_value","condition_discount_pct","max_bid"]

async def main():
    log.info("starting scrape (headless=%s)", HEADLESS)
    kwargs = {"headless": HEADLESS, "sandbox": False, "user_data_dir": PROFILE}
    if CHROME_PATH:
        kwargs["browser_executable_path"] = CHROME_PATH
    browser = await uc.start(**kwargs)
    tab = await browser.get("about:blank")
    await ensure_login(browser, tab)

    all_lots = []
    page = 0
    total = None
    while True:
        res = await fetch_in_page(tab, "/public/lots/search-results", json.dumps(build_body(page=page)))
        data = json.loads(res["t"])
        results = data["data"]["results"]
        total = results["totalElements"]
        content = results["content"] or []
        all_lots.extend(content)
        if len(all_lots) >= total or not content:
            break
        page += 1

    rows = [clean_lot(c) for c in all_lots]
    for r in rows:
        r.update(price_lot(r))
    log.info("total lots: %s | fetched: %s", total, len(rows))

    snap = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in rows:
        r["snapshot_date"] = snap

    csv_path = os.path.join(OUT, "copart_listings.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["snapshot_date"] + FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    json_path = os.path.join(OUT, "copart_listings.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1, default=str)

    hist_path = os.path.join(OUT, "history.csv")
    new = not os.path.exists(hist_path)
    with open(hist_path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["snapshot_date"] + FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)

    log.info("saved CSV: %s", csv_path)
    log.info("saved JSON: %s", json_path)
    log.info("appended history: %s", hist_path)

    # ---- summary ----
    priced = [r for r in rows if r["max_bid"] is not None]
    from collections import Counter
    log.info("max_bid computed for %s of %s lots", len(priced), len(rows))
    log.info("anchor used: %s", Counter(r["value_anchor"] for r in priced))
    log.info("by condition: %s", Counter((r["condition_code"] or "UNKNOWN").strip() for r in rows))
    log.info("by yard: %s", Counter(r["yard"] for r in rows))
    if priced:
        import statistics
        bids = [r["max_bid"] for r in priced]
        log.info("max_bid range: $%s - $%s | median $%s", min(bids), max(bids), round(statistics.median(bids)))

    browser.stop()
    # Let the event loop drain Chrome's subprocess pipes before shutdown.
    # Otherwise Windows' ProactorEventLoop prints harmless "Exception ignored
    # while calling deallocator ... I/O operation on closed pipe" noise at exit.
    await asyncio.sleep(1.5)
    log.info("scrape finished")

if __name__ == "__main__":
    asyncio.run(main())
