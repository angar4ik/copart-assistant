"""
Copart Tool — startup menu (colored, in-place refresh).

New workflow: you browse Copart yourself and the Chrome extension sends each
lot to the local server, which prices it on demand. This menu just runs the
server and offers a couple of maintenance helpers.

  [1] Run pricing server      -> server.py in a separate window
  [2] Re-price all lots       -> pricing.py (refresh all DB pricing)
  [3] Clear Auto.dev cache    -> pricing.py --clear-cache
  [4] Exit
"""
import os
import sys
import subprocess
import time
import urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config
import db

OUT = os.path.dirname(os.path.abspath(__file__))
PORT = 8000
log = config.get_logger("menu", "menu.log")


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
    os.system("cls" if os.name == "nt" else "clear")


def row(label, value, vcolor=C.BOLD):
    return "   %-13s  %s%s%s" % (C.GRAY + label + C.RST, vcolor, value, C.RST)


def server_running():
    try:
        urllib.request.urlopen("http://localhost:%d/" % PORT, timeout=1.5)
        return True
    except Exception:
        return False


def stats():
    d = db.stats()

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
        row("Last lot", d["last_scrape"] or "-"),
        row("Last pricing", d["last_pricing"] or "-"),
        row("Lots tracked", str(d["lots"]), C.BOLD),
        row("Lots priced", "%d  (%d have max bid)" % (d["priced_lots"], d["max_bid_lots"]), C.GREEN),
        row("Snapshots", "%d (history)" % d["snapshots"], C.DIM),
        row("API cache", "%d entries" % d["cache"], C.BOLD),
        row("Server", srv, ""),
        bar,
    ])


def menu():
    opt = C.YELLOW + C.BOLD
    items = [
        (opt + "[1]" + C.RST, "Run pricing server" + C.DIM + "   (new window)" + C.RST),
        (opt + "[2]" + C.RST, "Re-price all lots" + C.DIM + "   (Auto.dev)" + C.RST),
        (opt + "[3]" + C.RST, "Clear Auto.dev cache"),
        (C.DIM + "[4]" + C.RST, C.DIM + "Exit" + C.RST),
    ]
    return "\n".join("    %s  %s" % (k, v) for k, v in items)


def run_script(script, *args):
    path = os.path.join(OUT, script)
    log.info("running: %s %s", script, " ".join(args))
    print("\n" + C.CYAN + ">>> Running: %s" % script + C.RST + "\n")
    subprocess.run([sys.executable, path] + list(args))
    log.info("finished: %s", script)
    print("\n" + C.CYAN + ">>> Done: %s" % script + C.RST)


def run_server():
    if server_running():
        print("\n" + C.GREEN + "Server is already running at http://localhost:%d" % PORT + C.RST)
        time.sleep(0.8)
        return
    log.info("starting pricing server (new window)")
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
    db.init_db()
    while True:
        clear()
        print(stats())
        print()
        print(menu())
        print()
        choice = input("   Choose [1-4]: ").strip()
        log.info("menu choice: %s", choice)

        if choice == "1":
            run_server()
        elif choice == "2":
            run_script("pricing.py")
            pause()
        elif choice == "3":
            run_script("pricing.py", "--clear-cache")
            pause()
        elif choice in ("4", "q", "quit", "exit"):
            log.info("exit")
            clear()
            print(C.CYAN + C.BOLD + "Bye." + C.RST)
            break
        else:
            print("\n" + C.RED + "Invalid choice." + C.RST)
            time.sleep(0.8)


if __name__ == "__main__":
    main()
