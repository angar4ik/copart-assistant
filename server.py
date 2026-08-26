"""Local pricing server — the heart of the new workflow.

The Chrome extension POSTs a lot's details when its page opens; this server:
  1. upserts the lot + a snapshot into SQLite,
  2. prices it on demand (Auto.dev, cached) if it has no pricing yet,
  3. returns the full record so the extension can display the max bid.

Also serves /copart_listings_priced.json (all lots).

Run:  python3 server.py            (default http://localhost:8000)
      python3 server.py 9000       (custom port)
"""
import http.server
import socketserver
import os
import sys
import json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config
import db
import pricing

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
DIR = os.path.dirname(os.path.abspath(__file__))
log = config.get_logger("server", "server.log")


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_lot_row(data):
    """Turn raw extension data into a lot+snapshot row (parse title, map condition)."""
    title = (data.get("title") or "").strip()
    year, make, model = pricing.parse_title(title)
    # allow the extension to override parsed values if it knows better
    year = data.get("year") or year
    make = data.get("make") or make
    model = data.get("model") or model

    condition_code = (data.get("condition_code") or pricing.map_condition(data.get("condition")) or "").strip().upper()

    lot_number = data.get("lot_number")
    return {
        "lot_number": lot_number,
        "year": year,
        "make": make,
        "model": model,
        "title": title or None,
        "lot_url": ("https://www.copart.com/lot/%s" % lot_number) if lot_number else None,
        "snapshot_date": db.now(),
        "odometer": _num(data.get("odometer")),
        "condition_code": condition_code,
        "yard": data.get("yard"),
        "buy_now_price": _num(data.get("buy_now_price")),
        "est_retail_value": _num(data.get("est_retail_value")),
        "acv": _num(data.get("acv")),
        "repair_cost": _num(data.get("repair_cost")),
        "sale_date": data.get("sale_date"),
        "sale_time": data.get("sale_time"),
        "vin": data.get("vin"),
        "trim": data.get("trim"),
        "body_style": data.get("body_style"),
        "color": data.get("color"),
        "engine": data.get("engine"),
        "cylinders": data.get("cylinders"),
        "transmission": data.get("transmission"),
        "drivetrain": data.get("drivetrain"),
        "fuel": data.get("fuel"),
        "odometer_brand": data.get("odometer_brand"),
        "keys": data.get("keys"),
        "drive_status": data.get("drive_status"),
        "title_group": data.get("title_group"),
        "title_code": data.get("title_code"),
        "title_desc": data.get("title_desc"),
        "primary_damage": data.get("primary_damage"),
        "secondary_damage": data.get("secondary_damage"),
        "lot_condition": data.get("lot_condition"),
        "seller": data.get("seller"),
        "image": data.get("image"),
        "timezone": data.get("timezone"),
        "item_number": data.get("item_number"),
    }


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def end_headers(self):
        # allow the extension (content script on copart.com) to fetch cross-origin
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        # allow Private Network Access preflight (https page -> http://localhost)
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, code, obj):
        payload = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/copart_listings_priced.json", "/api/lots"):
            try:
                self._json(200, db.all_lots())
            except Exception as e:
                self._json(500, {"ok": False, "error": str(e)})
            return
        super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            self._json(400, {"ok": False, "error": str(e)})
            return

        if path == "/api/lot":
            lot_number = data.get("lot_number")
            if not lot_number:
                self._json(400, {"ok": False, "error": "lot_number is required"})
                return
            try:
                row = build_lot_row(data)
                db.save_lot(row)
                is_new = not db.has_pricing(lot_number)
                if is_new:
                    pr = pricing.price_lot(row)
                    if pr:
                        db.save_pricings([pr], db.now())
                record = db.get_lot_record(lot_number)
                # one clear pricing line per lot view
                title = (record or {}).get("title") or row.get("title") or ""
                mb = (record or {}).get("max_bid")
                mb_s = ("$%s" % format(int(mb), ",")) if mb is not None else "-"
                src = (record or {}).get("price_source") or "-"
                log.info("%s  lot %s  %s  ->  max_bid %s (%s)",
                         "PRICED" if is_new else "STORED", lot_number, title, mb_s, src)
            except Exception as e:
                log.warning("lot upsert failed: %s", e)
                self._json(500, {"ok": False, "error": str(e)})
                return
            self._json(200, {"ok": True, "record": record})
            return

        self._json(404, {"ok": False, "error": "unknown endpoint"})

    def log_message(self, fmt, *args):
        log.info(fmt % args)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    db.init_db()
    with Server(("", PORT), Handler) as httpd:
        log.info("pricing server running on http://localhost:%d", PORT)
        log.info("serving SQLite: %s", db.DB_FILE)
        print("Pricing server running:  http://localhost:%d" % PORT)
        print("Open a Copart lot page with the extension loaded to send data here.")
        print("Press Ctrl+C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            log.info("server stopped")
            print("\nServer stopped.")
