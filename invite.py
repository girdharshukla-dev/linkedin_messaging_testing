"""
New LinkedIn connection -> "Invite to follow" ShorterDB Page.

Runs inside YOUR logged-in browser profile (no passwords stored in code).
Deliberately low volume. Selectors are text/role based; if LinkedIn changes
its UI, adjust the few marked spots.

Setup:
    pip install playwright
    playwright install chromium

Usage:
    python invite.py --login   # opens browser, log in by hand, then Ctrl+C
    python invite.py --seed    # records current connections, invites nobody
    python invite.py           # checks every 20-40 min, invites new ones
    python invite.py --once    # single check, then exit (good for demos)
"""
import argparse
import random
import re
import sqlite3
import sys
import time

from playwright.sync_api import sync_playwright

COMPANY_ID = "143952888"
ADMIN_URL = f"https://www.linkedin.com/company/{COMPANY_ID}/admin/dashboard/"
CONNECTIONS_URL = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
PROFILE_DIR = "./li_profile"
DB_PATH = "invited.db"

MAX_PER_RUN = 3        # invites per check
MIN_CREDITS_LEFT = 5   # stop when the Page's credits drop to this
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
                if (m && text && !seen.has(m[1])) { seen.add(m[1]); out.push([m[1], text]); }
            });
            return out;
        }"""
    )
    return items[:limit]


def open_invite_dialog(page):
    page.goto(ADMIN_URL)
    page.wait_for_load_state("domcontentloaded")
    pause(3, 5)
    if blocked(page):
        raise RuntimeError("Login/checkpoint page. Stop and check manually.")
    page.get_by_role("link", name=re.compile("Invite to follow", re.I)).first.click()  # SELECTOR 1
    dialog = page.get_by_role("dialog")
    dialog.wait_for(timeout=15000)
    pause(2, 4)
    return dialog


def credits_left(dialog):
    m = re.search(r"(\d+)\s*/\s*(\d+)\s*credits", dialog.inner_text())
    return int(m.group(1)) if m else None


def invite_person(page, dialog, name):
    """Search the dialog for `name`, tick the first match, click Invite."""
    search = dialog.get_by_placeholder(re.compile("Search by name", re.I))  # SELECTOR 2
    search.fill("")
    search.fill(name)
    pause(2, 4)
    rows = dialog.locator("li").filter(has_text=name)
    if rows.count() == 0:
        return "not_found"
    box = rows.first.get_by_role("checkbox")  # SELECTOR 3
    if box.count() == 0:
        rows.first.locator("input[type=checkbox], label").first.click()
    else:
        box.first.check()
    pause(1, 2)
    dialog.get_by_role("button", name=re.compile(r"^Invite", re.I)).last.click()  # SELECTOR 4
    pause(2, 4)
    return "invited"


# ---------- main flows ----------
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
        dialog = open_invite_dialog(page)
        left = credits_left(dialog)
        print(f"Credits left: {left}")

        sent = 0
        for slug, name in new:
            if sent >= MAX_PER_RUN:
                print("Run cap reached; the rest wait for the next check.")
                break
            if left is not None and left - sent <= MIN_CREDITS_LEFT:
                print("Credits low, stopping.")
                break
            status = invite_person(page, dialog, name)
            record(con, slug, name, status)
            print(f"  {name}: {status}")
            if status == "invited":
                sent += 1
            pause(5, 10)
    finally:
        page.close()
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--seed", action="store_true")
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