"""
Copart Tool — interactive startup menu.

Shows project stats and lets you run each step:
  [1] Scrape Copart          -> copart_scrape.py
  [2] Grab pricing           -> pricing.py
  [3] Scrape + pricing       -> both
  [4] Run pricing server     -> server.py (http://localhost:8000)
  [5] Exit
"""
import json, os, sys, subprocess, time, datetime, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = os.path.dirname(os.path.abspath(__file__))
PORT = 8000

# ---- file paths ----
SCRAPE_JSON = os.path.join(OUT, "copart_listings.json")
PRICED_JSON = os.path.join(OUT, "copart_listings_priced.json")
CACHE_JSON = os.path.join(OUT, "auto_dev_cache.json")


def mtime(path):
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return "-"


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def server_running():
    try:
        urllib.request.urlopen("http://localhost:%d/" % PORT, timeout=1.5)
        return True
    except Exception:
        return False


def stats():
    s = load_json(SCRAPE_JSON)
    p = load_json(PRICED_JSON)
    c = load_json(CACHE_JSON)

    n_scraped = len(s) if isinstance(s, list) else 0
    n_priced = len(p) if isinstance(p, list) else 0
    n_maxbid = sum(1 for r in p if r.get("max_bid")) if isinstance(p, list) else 0
    n_cache = len(c) if isinstance(c, dict) else 0

    scrape_snap = "-"
    if isinstance(s, list) and s and s[0].get("snapshot_date"):
        scrape_snap = s[0]["snapshot_date"]

    lines = []
    lines.append("=" * 52)
    lines.append("  COPART TOOL")
    lines.append("=" * 52)
    lines.append("  Last scrape :  %s   (file %s)" % (scrape_snap, mtime(SCRAPE_JSON)))
    lines.append("  Last pricing:  %s" % mtime(PRICED_JSON))
    lines.append("  Lots scraped:  %d" % n_scraped)
    lines.append("  Lots priced :  %d  (%d have a max bid)" % (n_priced, n_maxbid))
    lines.append("  API cache   :  %d entries" % n_cache)
    lines.append("  Server      :  %s" % ("RUNNING  http://localhost:%d" % PORT if server_running() else "stopped"))
    lines.append("=" * 52)
    return "\n".join(lines)


def run_script(script, *args):
    path = os.path.join(OUT, script)
    print("\n>>> Running: %s %s\n" % (script, " ".join(args)))
    subprocess.run([sys.executable, path] + list(args))
    print("\n>>> Done: %s\n" % script)


def run_server():
    if server_running():
        print("\nServer is already running at http://localhost:%d\n" % PORT)
        return
    path = os.path.join(OUT, "server.py")
    print("\nStarting pricing server in a new window (close that window to stop it)...\n")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    subprocess.Popen([sys.executable, path], **kwargs)
    time.sleep(2)
    if server_running():
        print("Server is UP at http://localhost:%d\n" % PORT)
    else:
        print("Server window opened — check it for errors.\n")


MENU = """
  [1] Scrape Copart
  [2] Grab pricing (Auto.dev)
  [3] Scrape + pricing (both)
  [4] Run pricing server  (http://localhost:%d)
  [5] Exit
""" % PORT


def main():
    while True:
        print("\n" + stats())
        print(MENU)
        choice = input("Choose [1-5]: ").strip()
        if choice == "1":
            run_script("copart_scrape.py")
        elif choice == "2":
            run_script("pricing.py")
        elif choice == "3":
            run_script("copart_scrape.py")
            run_script("pricing.py")
        elif choice == "4":
            run_server()
        elif choice in ("5", "q", "quit", "exit"):
            print("\nBye.")
            break
        else:
            print("\nInvalid choice.")


if __name__ == "__main__":
    main()
