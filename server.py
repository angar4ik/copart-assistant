"""Local pricing server — serves this folder over HTTP so the Chrome extension
can read copart_listings_priced.json live (no re-packing the extension).

Run:  python3 server.py            (default http://localhost:8000)
      python3 server.py 9000       (custom port)
"""
import http.server, socketserver, os, sys, json, datetime, threading
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
DIR = os.path.dirname(os.path.abspath(__file__))
log = config.get_logger("server", "server.log")
BID_FILE = os.path.join(DIR, "live_bids.json")
_bid_lock = threading.Lock()


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

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            data = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
            return
        data["server_time"] = datetime.datetime.now().isoformat(timespec="seconds")
        try:
            append_bid(data)
        except Exception as e:
            log.warning("append bid failed: %s", e)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())

    def log_message(self, fmt, *args):
        log.info(fmt % args)


def append_bid(data):
    """Append a live-bid record to live_bids.json (thread-safe)."""
    with _bid_lock:
        records = []
        try:
            with open(BID_FILE, encoding="utf-8") as f:
                records = json.load(f)
        except Exception:
            records = []
        if not isinstance(records, list):
            records = []
        records.append(data)
        with open(BID_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=1, default=str)
    log.info("bid record: lot %s bid $%s", data.get("lot_number"), data.get("current_bid"))


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("", PORT), Handler) as httpd:
        log.info("pricing server running on http://localhost:%d", PORT)
        log.info("serving folder: %s", DIR)
        print("Pricing server running:  http://localhost:%d" % PORT)
        print("Serving folder: %s" % DIR)
        print("Press Ctrl+C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            log.info("server stopped")
            print("\nServer stopped.")
