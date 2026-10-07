"""
New LinkedIn connection tracker.

Usage:
    python invite.py --login   # opens browser, log in by hand, then Ctrl+C
    python invite.py --seed    # records current connections, sends nothing
    python invite.py --show    # shows connections not in invited.db
    python invite.py --once    # single check, then exit
    python invite.py            # checks every 20-40 min
"""

import argparse
import random
import sqlite3
import sys
import time

from playwright.sync_api import sync_playwright

CONNECTIONS_URL = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
PROFILE_DIR = "./li_profile"
DB_PATH = "invited.db"

CHECK_MINUTES = (20, 40)


# ---------- storage ----------
def db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS people ("
        "slug TEXT PRIMARY KEY, name TEXT, status TEXT, ts TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    return con


def known(con):
    return {r[0] for r in con.execute("SELECT slug FROM people")}


def record(con, slug, name, status):
    con.execute(
        "INSERT OR REPLACE INTO people (slug, name, status) VALUES (?,?,?)",
        (slug, name, status),
    )
    con.commit()


# ---------- helpers ----------
def pause(a=3, b=8):
    time.sleep(random.uniform(a, b))


def blocked(page):
    u = page.url
    return any(k in u for k in ("checkpoint", "authwall", "/login", "captcha"))


def recent_connections(page, limit=15):
    """Returns [(slug, name)] newest first, from the Connections page."""
    page.goto(CONNECTIONS_URL)
    page.wait_for_load_state("domcontentloaded")
    pause(4, 7)
    if blocked(page):
        raise RuntimeError("LinkedIn showed a login/checkpoint page. Stop and check manually.")
    page.mouse.wheel(0, 1200)
    pause(2, 4)
    items = page.evaluate(
        """() => {
            const out = [], seen = new Set();
            document.querySelectorAll('a[href*="/in/"]').forEach(a => {
                const m = a.href.match(/\\/in\\/([^/?#]+)/);
                const text = (a.innerText || '').trim().split('\\n')[0].trim();
                if (m && text && !seen.has(m[1])) {
                    seen.add(m[1]);
                    out.push([m[1], text]);
                }
            });
            return out;
        }"""
    )
    return items[:limit]


# ---------- main flows ----------
def show_new(ctx):
    con = db()
    page = ctx.new_page()
    try:
        people = recent_connections(page)
        have = known(con)
        new = [(s, n) for s, n in people if s not in have]

        for slug, name in new:
            print(f"{name} -> {slug}")
    finally:
        page.close()
        con.close()


def check_once(ctx, seed=False):
    con = db()
    page = ctx.new_page()
    try:
        people = recent_connections(page)
        have = known(con)
        new = [(s, n) for s, n in people if s not in have]

        if seed:
            for s, n in people:
                record(con, s, n, "baseline")
            print(f"Seeded {len(people)} existing connections. Nobody invited.")
            return

        if not new:
            print("No new connections.")
            return

        print(f"New connections: {[n for _, n in new]}")

        for slug, name in new:
            record(con, slug, name, "new")
            print(f"  {name}: recorded")

    finally:
        page.close()
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE_DIR, headless=False)
        try:
            if args.login:
                ctx.new_page().goto("https://www.linkedin.com/login")
                print("Log in by hand, then press Ctrl+C here.")
                while True:
                    time.sleep(1)
            elif args.show:
                show_new(ctx)
            elif args.seed:
                check_once(ctx, seed=True)
            elif args.once:
                check_once(ctx)
            else:
                while True:
                    check_once(ctx)
                    wait = random.uniform(*CHECK_MINUTES) * 60
                    print(f"Next check in {wait/60:.0f} min")
                    time.sleep(wait)
        except KeyboardInterrupt:
            pass
        except RuntimeError as e:
            print(f"STOPPED: {e}")
            sys.exit(1)
        finally:
            ctx.close()


if __name__ == "__main__":
    main()

