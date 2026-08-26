"""
Copart Tool — interactive startup menu (colored, in-place refresh).

Shows project stats and lets you run each step:
  [1] Scrape Copart          -> copart_scrape.py
  [2] Grab pricing           -> pricing.py
  [3] Scrape + pricing       -> both
  [4] Run pricing server     -> server.py in a separate window
  [5] Exit
"""
import json, os, sys, subprocess, time, datetime, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = os.path.dirname(os.path.abspath(__file__))
PORT = 8000

# ---- ANSI colors ----
def enable_vt():
    """Turn on Windows virtual-terminal processing so ANSI colors render in cmd."""
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            m = ctypes.c_uint32()
            k.GetConsoleMode(h, ctypes.byref(m))
            k.SetConsoleMode(h, m.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            pass


class C:
    RST = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"


def clear():
    """Clear the console so the menu redraws in place (no duplicate copies)."""
    os.system("cls" if os.name == "nt" else "clear")


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


def row(label, value, vcolor=C.BOLD):
    return "   %-13s  %s%s%s" % (C.GRAY + label + C.RST, vcolor, value, C.RST)


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

    if server_running():
        srv = C.GREEN + C.BOLD + "RUNNING   http://localhost:%d" % PORT + C.RST
    else:
        srv = C.RED + "stopped" + C.RST

    bar = C.CYAN + C.BOLD + "=" * 50 + C.RST
    head = C.CYAN + C.BOLD + "   COPART ASSISTANT" + C.RST
    return "\n".join([
        bar,
        head,
        bar,
        row("Last scrape", scrape_snap + "  " + C.DIM + "(" + mtime(SCRAPE_JSON) + ")" + C.RST),
        row("Last pricing", mtime(PRICED_JSON)),
        row("Lots scraped", str(n_scraped), C.BOLD),
        row("Lots priced", "%d  (%d have max bid)" % (n_priced, n_maxbid), C.GREEN),
        row("API cache", "%d entries" % n_cache, C.BOLD),
        row("Server", srv, ""),
        bar,
    ])


def menu():
    running = server_running()
    opt = C.YELLOW + C.BOLD
    items = [
        (opt + "[1]" + C.RST, "Scrape Copart"),
        (opt + "[2]" + C.RST, "Grab pricing (Auto.dev)"),
        (opt + "[3]" + C.RST, "Scrape + pricing (both)"),
        (opt + "[4]" + C.RST, "Run pricing server" + C.DIM + "   (new window)" + C.RST),
        (C.DIM + "[5]" + C.RST, C.DIM + "Exit" + C.RST),
    ]
    return "\n".join("    %s  %s" % (k, v) for k, v in items)


def run_script(script):
    path = os.path.join(OUT, script)
    print("\n" + C.CYAN + ">>> Running: %s" % script + C.RST + "\n")
    subprocess.run([sys.executable, path])
    print("\n" + C.CYAN + ">>> Done: %s" % script + C.RST)


def run_server():
    if server_running():
        print("\n" + C.GREEN + "Server is already running at http://localhost:%d" % PORT + C.RST)
        time.sleep(0.8)
        return
    path = os.path.join(OUT, "server.py")
    print("\n" + C.CYAN + "Starting pricing server in a new window (close that window to stop it)..." + C.RST)
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    subprocess.Popen([sys.executable, path], **kwargs)
    time.sleep(1.5)
    if server_running():
        print(C.GREEN + "Server is UP at http://localhost:%d" % PORT + C.RST)
    else:
        print(C.RED + "Server window opened — check it for errors." + C.RST)
    time.sleep(0.8)


def pause():
    try:
        input("\n" + C.GRAY + "Press Enter to return to menu..." + C.RST)
    except (EOFError, KeyboardInterrupt):
        pass


def main():
    enable_vt()
    while True:
        clear()
        print(stats())
        print()
        print(menu())
        print()
        choice = input("   Choose [1-5]: ").strip()

        if choice == "1":
            run_script("copart_scrape.py")
            pause()
        elif choice == "2":
            run_script("pricing.py")
            pause()
        elif choice == "3":
            run_script("copart_scrape.py")
            run_script("pricing.py")
            pause()
        elif choice == "4":
            run_server()
        elif choice in ("5", "q", "quit", "exit"):
            clear()
            print(C.CYAN + C.BOLD + "Bye." + C.RST)
            break
        else:
            print("\n" + C.RED + "Invalid choice." + C.RST)
            time.sleep(0.8)


if __name__ == "__main__":
    main()
