// Copart Max Bid — background service worker.
// All server calls happen here (extension context, not subject to the page's
// CSP / mixed-content rules). Only market pricing is requested — no bid tracking.
const SERVERS = ["http://localhost:8000", "http://127.0.0.1:8000"];

chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  if (msg && msg.type === "postLot") {
    postJson("/api/lot", msg.data)
      .then(function (resp) { sendResponse(resp); })
      .catch(function (e) { sendResponse({ ok: false, error: String(e && e.message || e) }); });
    return true;
  }
});

async function postJson(path, data) {
  let lastErr = null;
  for (const base of SERVERS) {
    try {
      const res = await fetch(base + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      return await res.json();
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr || new Error("server unreachable");
}
