"""
New LinkedIn connection tracker + auto message.

Usage:
    python invite.py --login     # opens browser, log in by hand, then Ctrl+C
    python invite.py --seed      # records current connections, sends nothing
    python invite.py --show      # shows connections not in invited.db
    python invite.py --dry-run   # finds new connections, types the message, does NOT send
    python invite.py --once      # single check: message new connections, then exit
    python invite.py --retry     # forget failed attempts, then run one check
    python invite.py             # checks every 20-40 min

Edit COMPANY_PAGE_URL and MESSAGE_TEMPLATE below before running.
"""

import argparse
import random
import re
import sqlite3
import sys
import time

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

CONNECTIONS_URL = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
PROFILE_DIR = "./li_profile"
DB_PATH = "invited.db"

COMPANY_PAGE_URL = "https://www.linkedin.com/company/YOUR-PAGE-NAME/"
MESSAGE_TEMPLATE = (
    "Hi {first_name}, thanks for connecting! "
    "If you'd like to see what we're building, here's our company page: {page_url}"
)
MAX_PER_RUN = 3          # messages sent per check
CHECK_MINUTES = (20, 40)


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


def forget_failed(con):
    con.execute("DELETE FROM people WHERE status NOT IN ('baseline', 'messaged')")
    con.commit()


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


def build_message(name):
    first = name.split()[0] if name else "there"
    return MESSAGE_TEMPLATE.format(first_name=first, page_url=COMPANY_PAGE_URL)


def send_message(page, slug, text, dry_run=False):
    """Open the person's profile, type the message, send it.
    Returns a status string: 'messaged', 'dry_run', or a failure reason."""
    page.goto(f"https://www.linkedin.com/in/{slug}/")
    page.wait_for_load_state("domcontentloaded")
    pause(3, 6)
    if blocked(page):
        raise RuntimeError("LinkedIn showed a login/checkpoint page. Stop and check manually.")

    # SELECTOR 1: the "Message" button on the profile
    msg_btn = page.get_by_role("button", name=re.compile(r"^Message\b", re.I))
    if msg_btn.count() == 0:
        msg_btn = page.get_by_role("link", name=re.compile(r"^Message\b", re.I))
    if msg_btn.count() == 0:
        return "failed_no_message_button"
    msg_btn.first.click()
    pause(2, 4)

    # SELECTOR 2: the text box in the chat window that opens
    box = page.get_by_role("textbox", name=re.compile(r"write a message", re.I)).last
    try:
        box.wait_for(timeout=10000)
    except PWTimeout:
        return "failed_no_textbox"
    box.click()
    box.fill(text)
    pause(1, 3)

    if dry_run:
        return "dry_run"

    # SELECTOR 3: the Send button
    send_btn = page.get_by_role("button", name=re.compile(r"^Send$", re.I)).last
    if send_btn.is_disabled():
        return "failed_send_disabled"
    send_btn.click()
    pause(2, 4)
    return "messaged"


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


def check_once(ctx, seed=False, dry_run=False):
    con = db()
    page = ctx.new_page()
    try:
        people = recent_connections(page)
        have = known(con)
        new = [(s, n) for s, n in people if s not in have]

        if seed:
            for s, n in people:
                record(con, s, n, "baseline")
            print(f"Seeded {len(people)} existing connections. Nobody messaged.")
            return

        if not new:
            print("No new connections.")
            return

        print(f"New connections: {[n for _, n in new]}")

        sent = 0
        for slug, name in new:
            if sent >= MAX_PER_RUN:
                print("Run limit reached; the rest wait for the next check.")
                break
            text = build_message(name)
            try:
                status = send_message(page, slug, text, dry_run=dry_run)
            except PWTimeout:
                status = "failed_timeout"

            if dry_run:
                print(f"  {name}: DRY RUN, typed but not sent -> {text!r}")
            else:
                record(con, slug, name, status)
                print(f"  {name}: {status}")
            sent += 1
            pause(8, 15)

    finally:
        page.close()
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--retry", action="store_true")
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
            elif args.dry_run:
                check_once(ctx, dry_run=True)
            elif args.retry:
                con = db()
                forget_failed(con)
                con.close()
                check_once(ctx)
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
