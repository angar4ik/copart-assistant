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
    const rows = [
      ["Condition", cond],
      ["Market value", fmt(d.market_price) + (d.market_scope ? " (" + d.market_scope + ")" : "")],
      ["Discount", d.condition_discount_pct != null ? d.condition_discount_pct + "%" : "—"],
    ];
    if (Number(d.buy_now_price) > 0) rows.push(["Buy-It-Now", fmt(d.buy_now_price)]);
    if (d.current_bid != null) rows.push(["Current bid", fmt(d.current_bid)]);

    const rowHtml = rows.map(function (r) {
      return '<div class="cmb-row"><span class="cmb-k">' + r[0] + '</span><span class="cmb-v">' + r[1] + "</span></div>";
    }).join("");

    const warnHtml = over ? '<div class="cmb-warn">&#9888; Current bid is above your max</div>' : "";
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

  async function render(lot, force) {
    const my = ++renderSeq;
    injectStyles();
    showMsg(lot, "Loading pricing…");
    try {
      const p = await loadPricing(force);
      if (my !== renderSeq) return; // stale render, ignore
      const d = p.map[lot];
      if (d) showRow(lot, d, p.asof);
      else showMsg(lot, "No pricing data for this lot.");
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
})();
