// Copart Max Bid — background service worker.
// Fetches pricing from the local server (extension-origin request, not subject to
// the page's CSP / mixed-content rules) and hands it back to the content script.
const SERVERS = ["http://localhost:8000", "http://127.0.0.1:8000"];

chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  if (msg && msg.type === "getPricing") {
    fetchPricing()
      .then(function (resp) { sendResponse(resp); })
      .catch(function (e) { sendResponse({ ok: false, error: String(e && e.message || e) }); });
    return true;
  }
  if (msg && msg.type === "postBid") {
    postBid(msg.data)
      .then(function (resp) { sendResponse(resp); })
      .catch(function (e) { sendResponse({ ok: false, error: String(e && e.message || e) }); });
    return true;
  }
});

async function postBid(data) {
  let lastErr = null;
  for (const base of SERVERS) {
    try {
      const res = await fetch(base + "/api/bid", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      return { ok: true };
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr || new Error("server unreachable");
}

async function fetchPricing() {
  let lastErr = null;
  for (const base of SERVERS) {
    try {
      const res = await fetch(base + "/copart_listings_priced.json", { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const arr = await res.json();
      return { ok: true, arr: arr };
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr || new Error("server unreachable");
}
