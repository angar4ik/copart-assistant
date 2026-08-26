// Copart Max Bid — content script (server-backed).
// Fetches pricing from the local server (http://localhost:8000/copart_listings_priced.json)
// and shows a suggested max bid for the current lot. No Auto.dev calls at browse time.
(function () {
  "use strict";

  const PANEL_ID = "copart-maxbid-panel";
  const CACHE_MS = 60000; // re-fetch at most once a minute unless forced

  const COND_LABEL = {
    "CERT-D": "Run & Drive",
    "CERT-E": "Enhanced (mechanical issue)",
    "CERT-S": "Engine Start (does not drive)",
    "": "Unknown (assume non-runner)",
  };

  let PRICING = null;   // { asof, map }
  let lastLot = null;
  let forceRefresh = false;
  let renderSeq = 0;

  function getLotNumber() {
    const m = location.pathname.match(/\/lot\/(\d+)/);
    return m ? m[1] : null;
  }

  function fmt(x) {
    if (x === null || x === undefined || x === "") return "—";
    return "$" + Math.round(Number(x)).toLocaleString("en-US");
  }

  async function loadPricing(force) {
    const now = Date.now();
    if (!force && PRICING && now - PRICING.ts < CACHE_MS) return PRICING;
    const resp = await requestPricing();
    const arr = resp.arr || [];
    const map = {};
    let asof = "";
    arr.forEach(function (r) {
      if (r && r.lot_number != null) {
        map[String(r.lot_number)] = r;
        if (!asof) asof = r.snapshot_date || "";
      }
    });
    PRICING = { asof: asof, map: map, ts: now };
    return PRICING;
  }

  function requestPricing() {
    return new Promise(function (resolve, reject) {
      chrome.runtime.sendMessage({ type: "getPricing" }, function (resp) {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        if (resp && resp.ok) resolve(resp);
        else reject(new Error((resp && resp.error) || "server unreachable"));
      });
    });
  }

  function injectStyles() {
    if (document.getElementById("cmb-style")) return;
    const css =
      "#" + PANEL_ID + "{position:fixed;right:16px;bottom:16px;width:300px;z-index:2147483000;" +
      "background:#0f172a;color:#e2e8f0;border:1px solid #1e293b;border-radius:12px;" +
      "font:13px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;" +
      "box-shadow:0 12px 40px rgba(0,0,0,.5);overflow:hidden;}" +
      "#" + PANEL_ID + " .cmb-head{display:flex;align-items:center;gap:8px;padding:10px 12px;" +
      "background:#1e293b;font-weight:600;font-size:13px;}" +
      "#" + PANEL_ID + " .cmb-lot{color:#94a3b8;font-weight:400;font-size:12px;}" +
      "#" + PANEL_ID + " .cmb-btns{margin-left:auto;display:flex;gap:8px;align-items:center;}" +
      "#" + PANEL_ID + " .cmb-refresh,#" + PANEL_ID + " .cmb-close{cursor:pointer;color:#94a3b8;" +
      "font-size:16px;line-height:1;background:none;border:none;padding:0;}" +
      "#" + PANEL_ID + " .cmb-refresh:hover,#" + PANEL_ID + " .cmb-close:hover{color:#fff;}" +
      "#" + PANEL_ID + " .cmb-body{padding:12px;}" +
      "#" + PANEL_ID + " .cmb-title{font-weight:600;margin-bottom:8px;color:#fff;}" +
      "#" + PANEL_ID + " .cmb-row{display:flex;justify-content:space-between;padding:3px 0;color:#cbd5e1;}" +
      "#" + PANEL_ID + " .cmb-k{color:#64748b;}" +
      "#" + PANEL_ID + " .cmb-v{font-weight:500;}" +
      "#" + PANEL_ID + " .cmb-max{font-size:28px;font-weight:700;color:#4ade80;text-align:center;margin-top:10px;}" +
      "#" + PANEL_ID + " .cmb-max-label{text-align:center;color:#64748b;font-size:11px;margin-bottom:6px;}" +
      "#" + PANEL_ID + " .cmb-warn{background:#7f1d1d;color:#fecaca;border:1px solid #dc2626;" +
      "border-radius:8px;padding:6px 8px;margin-top:8px;font-size:12px;}" +
      "#" + PANEL_ID + " .cmb-warn-amber{background:#78350f;color:#fde68a;border:1px solid #d97706;" +
      "border-radius:8px;padding:6px 8px;margin-top:8px;font-size:12px;}" +
      "#" + PANEL_ID + " .cmb-foot{color:#475569;font-size:10px;margin-top:10px;text-align:center;}" +
      "#" + PANEL_ID + " .cmb-msg{color:#94a3b8;text-align:center;padding:16px;}";
    const s = document.createElement("style");
    s.id = "cmb-style";
    s.textContent = css;
    document.head.appendChild(s);
  }

  function headerHtml(lot) {
    return '<div class="cmb-head"><span>Copart Max Bid</span>' +
      '<span class="cmb-lot">Lot #' + lot + "</span>" +
      '<span class="cmb-btns">' +
      '<button class="cmb-refresh" title="Refresh">&circlearrowright;</button>' +
      '<button class="cmb-close" title="Hide">&times;</button>' +
      "</span></div>";
  }

  function mountPanel(lot, bodyHtml) {
    const el = document.createElement("div");
    el.id = PANEL_ID;
    el.innerHTML = headerHtml(lot) + '<div class="cmb-body">' + bodyHtml + "</div>";
    el.querySelector(".cmb-close").addEventListener("click", function () { el.remove(); });
    el.querySelector(".cmb-refresh").addEventListener("click", function () {
      forceRefresh = true;
      tick();
    });
    document.body.appendChild(el);
  }

  function showRow(lot, d, asof) {
    const over = d.current_bid != null && d.max_bid != null && Number(d.current_bid) > Number(d.max_bid);
    const cond = COND_LABEL[(d.condition_code || "").trim().toUpperCase()] || COND_LABEL[""];
    const odo = d.odometer != null && Number(d.odometer) > 0
      ? Math.round(Number(d.odometer)).toLocaleString("en-US") + " mi"
      : "—";
    const rows = [
      ["Condition", cond],
      ["Odometer", odo],
      ["Market value", fmt(d.market_price) + (d.market_scope ? " (" + d.market_scope + ")" : "")],
      ["Discount", d.condition_discount_pct != null ? d.condition_discount_pct + "%" : "—"],
    ];
    if (Number(d.buy_now_price) > 0) rows.push(["Buy-It-Now", fmt(d.buy_now_price)]);
    if (d.current_bid != null) rows.push(["Current bid", fmt(d.current_bid)]);

    const rowHtml = rows.map(function (r) {
      return '<div class="cmb-row"><span class="cmb-k">' + r[0] + '</span><span class="cmb-v">' + r[1] + "</span></div>";
    }).join("");

    const warns = [];
    if (over) warns.push('<div class="cmb-warn">&#9888; Current bid is above your max</div>');
    if (window.innerWidth < 1025) {
      warns.push('<div class="cmb-warn-amber">&#9888; Window too narrow &mdash; resize to &ge;1025px to track live bid</div>');
    }
    if (d.price_source && d.price_source !== "auto.dev") {
      warns.push('<div class="cmb-warn-amber">&#9888; No Auto.dev price &mdash; using Copart estimate</div>');
    } else if (d.market_mileage_adjusted === false) {
      warns.push('<div class="cmb-warn-amber">&#9888; High mileage &mdash; no comparable comps, price may be off</div>');
    } else if (d.market_mileage_adjusted == null) {
      warns.push('<div class="cmb-warn-amber">&#9888; No odometer data &mdash; price not mileage-adjusted</div>');
    }
    const warnHtml = warns.join("");
    const src = (d.price_source || "") + (asof ? " &middot; " + asof : "");

    mountPanel(lot,
      '<div class="cmb-title">' + (d.title || "—") + "</div>" +
      rowHtml +
      '<div class="cmb-max">' + fmt(d.max_bid) + "</div>" +
      '<div class="cmb-max-label">suggested max bid</div>' +
      warnHtml +
      '<div class="cmb-foot">' + src + "</div>");
  }

  function showMsg(lot, msg) {
    mountPanel(lot, '<div class="cmb-msg">' + msg + "</div>");
  }

  // ---- live bid collection ----
  function scrapePage() {
    // Copart bug: the bid/lot details are hidden when viewport is under 1025px.
    const tooNarrow = window.innerWidth < 1025;
    const text = (tooNarrow || !document.body) ? "" : document.body.innerText;
    let bid = null;
    const bi = text.indexOf("Current bid");
    if (bi >= 0) {
      const m = text.slice(bi, bi + 200).match(/\$([\d,]+)/);
      if (m) bid = parseInt(m[1].replace(/,/g, ""), 10);
    }
    const cd = (text.match(/(\d+D\s*\d+H\s*\d+min)/i) || [])[1] || null;
    const st = (text.match(/(On approval|Minimum Bid|Pure sale|Sold|Not on sale|On minimum bid)/i) || [])[1] || null;
    let odo = null;
    const om = text.match(/Odometer:\s*([\d,]+)\s*mi/i);
    if (om) odo = parseInt(om[1].replace(/,/g, ""), 10);
    return { current_bid: bid, countdown: cd, sale_status: st, odometer: odo, too_narrow: tooNarrow };
  }

  function buildRecord(lot, d, scrape) {
    const rec = { lot_number: lot };
    if (d) {
      rec.title = d.title || null;
      rec.year = d.year != null ? d.year : null;
      rec.make = d.make || null;
      rec.model = d.model || null;
      rec.condition_code = d.condition_code || null;
      rec.title_group = d.title_group || null;
      rec.yard = d.yard || null;
      rec.market_price = d.market_price != null ? Number(d.market_price) : null;
      rec.max_bid = d.max_bid != null ? Number(d.max_bid) : null;
      rec.odometer = (d.odometer != null && Number(d.odometer) > 0) ? Number(d.odometer) : (scrape.odometer || null);
    } else {
      rec.title = (document.title || "").split("|")[0].trim() || null;
      rec.odometer = scrape.odometer || null;
    }
    rec.current_bid = scrape.current_bid;
    rec.countdown = scrape.countdown;
    rec.sale_status = scrape.sale_status;
    rec.client_time = new Date().toISOString();
    return rec;
  }

  let lastSentKey = null;

  function collectAndSend(lot, d) {
    try {
      const scrape = scrapePage();
      if (scrape.too_narrow) return; // Copart hides bid below 1025px width
      const rec = buildRecord(lot, d, scrape);
      const key = lot + "|" + rec.current_bid + "|" + rec.sale_status;
      if (key === lastSentKey) return;
      lastSentKey = key;
      chrome.runtime.sendMessage({ type: "postBid", data: rec }, function () {
        if (chrome.runtime.lastError) { /* server may be off; ignore */ }
      });
    } catch (e) { /* ignore */ }
  }

  async function render(lot, force) {
    const my = ++renderSeq;
    injectStyles();
    showMsg(lot, "Loading pricing…");
    try {
      const p = await loadPricing(force);
      if (my !== renderSeq) return; // stale render, ignore
      const d = p.map[lot];
      if (d) {
        showRow(lot, d, p.asof);
        collectAndSend(lot, d);
      } else {
        showMsg(lot, "No pricing data for this lot.");
        collectAndSend(lot, null);
      }
    } catch (e) {
      if (my !== renderSeq) return;
      showMsg(lot, "Pricing server not running.<br>Start it from the menu (run pricing server), then click &#8635;.");
    }
  }

  function tick() {
    const lot = getLotNumber();
    if (!lot) {
      const el = document.getElementById(PANEL_ID);
      if (el) el.remove();
      lastLot = null;
      return;
    }
    if (lot === lastLot && !forceRefresh) return;
    forceRefresh = false;
    lastLot = lot;
    render(lot, false);
  }

  // Copart is an SPA — watch for URL changes (no full reload between lots).
  setInterval(tick, 1000);
  tick();

  // Sense bid changes in near-real-time: watch the DOM and re-collect immediately
  // when the bid (or sale status) changes. collectAndSend() dedupes by value.
  let bidDebounce = null;
  const bidObserver = new MutationObserver(function () {
    if (bidDebounce) return;
    bidDebounce = setTimeout(function () {
      bidDebounce = null;
      const lot = getLotNumber();
      if (!lot) return;
      collectAndSend(lot, PRICING ? PRICING.map[lot] : null);
    }, 300);
  });
  bidObserver.observe(document.body, { childList: true, subtree: true, characterData: true });

  // Safety net in case a change slips past the observer.
  setInterval(function () {
    const lot = getLotNumber();
    if (!lot) return;
    collectAndSend(lot, PRICING ? PRICING.map[lot] : null);
  }, 60000);
})();
