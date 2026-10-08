# LinkedIn New-Connection Follow-Up (Proof of Concept)

When someone new connects with me on LinkedIn, this script detects them and sends
them a message with my company page link.

## The goal

The intended flow is:

1. Someone connects with me on LinkedIn.
2. They automatically get an **"Invite to follow"** for my company page.

---

## 2. What I could not find

After reading the docs and searching, I found **no official API** for:

- **Sending an "Invite to follow" for a company page.** The Community Management API can
  read follower statistics, but I found no endpoint that sends follow invitations.
- **Being notified when someone connects with me.** I found no webhook or event for new
  connections available to ordinary developers.
- **Listing my connections or sending messages**, outside of approved partner programs.

So even with approval for the open-access products, the "Invite to follow" step has
no API to call.

## 3. How "Invite to follow" is expected to work (the LinkedIn UI)

Based on LinkedIn's Help Center and other sources I read:

- A person can invite their **1st-degree connections** to follow a company page.
- Page admins can do this for their own page. LinkedIn has also opened it to members
  for pages with **5,000 or fewer followers**.
- Pages get **monthly invitation credits**, shared across all admins of that page.
- Invites go to **your own connections only**. A page cannot invite strangers.
- A company page has no login of its own. It is managed through personal profiles that
  hold an admin role. The profile that creates the page becomes its super admin.

## 4. Why this demo sends a message instead

I tried to run the demo on a test account, but LinkedIn would not let that account
create a Page because it requires workplace verification first.

So the demo covers the same trigger-and-action idea with a step LinkedIn does allow
from the interface:

> new connection detected -> message them a link to the company page

In a real deployment the final step would be swapped for "Invite to follow" (done by a
page admin from their own account), or replaced with an official API if LinkedIn ever
provides one.

---

## 5. How the script works

File: `invite.py` (Python + Playwright + SQLite)

1. **Browser session.** Playwright opens a real Chromium window using a saved profile
   folder (`li_profile`). I log in by hand once; no password is stored in the code.
2. **Detect.** It opens the Connections page (newest first) and reads the profile links
   to build a list of people.
3. **Compare.** It checks that list against a local SQLite database (`invited.db`).
   Anyone not in the database is a new connection.
4. **Message.** For each new person (up to 3 per check), it opens their profile, clicks
   Message, types the templated text, and clicks Send.
5. **Remember.** It saves the result so nobody is messaged twice.
6. **Repeat.** In continuous mode, it waits a random 20 to 40 minutes and checks again.

### Database statuses

| Status | Meaning |
|---|---|
| `baseline` | Already a connection when the script was first seeded |
| `messaged` | Message sent |
| `failed_*` | Something went wrong (no Message button, no text box, Send disabled, timeout) |

### Safety behaviour

- `--seed` records existing connections first, so the first real run does not message
  everyone I already know.
- `--dry-run` types the message but does not send or save anything.
- A cap of 3 messages per check, with random pauses between actions.
- If LinkedIn shows a login or verification page, the script stops instead of
  continuing.
- Failed attempts are not retried automatically. `--retry` clears them for another try.

---

## 6. Setup and usage

```bash
pip install playwright
playwright install chromium
```

Edit these two lines near the top of `invite.py`:

```python
COMPANY_PAGE_URL = "https://www.linkedin.com/company/YOUR-PAGE-NAME/"
MESSAGE_TEMPLATE = "Hi {first_name}, thanks for connecting! ... {page_url}"
```

Run in this order:

```bash
python invite.py --login     # log in by hand in the window, then Ctrl+C
python invite.py --seed      # record current connections, message nobody
python invite.py --show      # preview who counts as new (read-only)
python invite.py --dry-run   # type messages for new people, send nothing
python invite.py --once      # one real check
python invite.py --retry     # clear failures, run one check
python invite.py             # run continuously (20-40 min between checks)
```

## 7. Limitations

- **Not an official integration.** It drives the LinkedIn website the way a person would.
  Run it on a test account, at low volume.
- **Selectors can break.** The Message button, text box and Send button are found by
  role and label (marked `SELECTOR 1` to `3` in the code). If LinkedIn changes its
  pages, those lines need adjusting.
- **Not real-time.** New connections are found on each check, not instantly.
- **"Messaged" means Send was clicked.** The script does not confirm delivery.
- **Names with titles** (for example "Dr. Rahul Sharma") produce an awkward greeting
  because only the first word is used.
- **The Connections page may include extra profile links** besides connections, since
  detection is based on finding profile links.

