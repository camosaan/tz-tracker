import os, re, sys
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
ROLE_ID = os.environ["DISCORD_ROLE_ID"]

LOCAL_TZ = os.environ.get("LOCAL_TZ", "Europe/London")
DEBUG = os.environ.get("DEBUG", "0").lower() in {"1", "true", "yes"}
FORCE = os.environ.get("FORCE_SEND", "false").lower() in {"1", "true", "yes"}

# Comma-separated env overrides defaults
DEFAULT_TERMS = ["Burial Grounds", "Crypt", "Mausoleum", "Far Oasis"]
WATCH_TERMS = [t.strip() for t in os.environ.get("WATCH_TERMS", ",".join(DEFAULT_TERMS)).split(",") if t.strip()]
WATCH_TERMS_LC = {t.lower() for t in WATCH_TERMS}

# When to send (local time): :05 (initial detect), :30, :45, :55
SEND_MINUTES = {5, 30, 45, 55}

URL = "https://d2emu.com/tz"


# ----------------------- Playwright extraction -----------------------
def fetch_next_tz_playwright() -> tuple[str | None, list[str]]:
    """
    Returns (left_column_text, [zone names]) for the Next Terror Zone block.
    Reliably targets the two columns in the .container.my-4 .row layout.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(20000)
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)  # small settle time for JS/CSS

        # The page renders both "Current" and "Next" blocks with similar markup.
        # The block we want for "Next" is the SECOND .container.my-4 with that two-col layout.
        # But to be robust, we read ALL such rows and pick the one whose left column contains "Next Terror Zone".
        rows = page.locator("div.container.my-4 div.row")
        count = rows.count()
        left_text, zones = None, []

        for i in range(count):
            left = rows.nth(i).locator("div.col").nth(0)
            right = rows.nth(i).locator("div.col").nth(1)

            if not left.is_visible():
                continue

            left_txt = left.inner_text().strip()
            if "Next Terror Zone" not in left_txt:
                continue

            # Found the right row — extract zone names from the right column list
            zone_links = right.locator("ul.list-unstyled li a")
            zones_found = [z.strip() for z in zone_links.all_inner_texts() if z.strip()]

            left_text, zones = left_txt, zones_found
            break

        browser.close()
        return left_text, zones


# ----------------------- Helpers -----------------------
def parse_next_timestamp(left_text: str, tz: ZoneInfo) -> datetime | None:
    """
    Extract "DD/MM/YYYY, HH:MM:SS" OR "M/D/YYYY, HH:MM:SS" from the left column text
    and attach the local tz.
    """
    if not left_text:
        return None
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2}:\d{2})", left_text)
    if not m:
        return None
    d, t = m.group(1), m.group(2)
    for fmt in ("%d/%m/%Y, %H:%M:%S", "%m/%d/%Y, %H:%M:%S"):
        try:
            dt_naive = datetime.strptime(f"{d}, {t}", fmt)
            return dt_naive.replace(tzinfo=tz)
        except ValueError:
            continue
    return None


def should_send_now(now_local: datetime) -> bool:
    return FORCE or (now_local.minute in SEND_MINUTES)


def send_webhook(zones: list[str], start_dt_local: datetime, left_text: str):
    epoch = int(start_dt_local.timestamp())
    abs_tag = f"<t:{epoch}:t>"
    rel_tag = f"<t:{epoch}:R>"
    mention = f"<@&{ROLE_ID}>"
    zone_names = ", ".join(zones)

    content = (
        f"{mention} **Terror Zone match: {zone_names}**\n"
        f"Starts at {abs_tag} ({rel_tag})\n"
        f"Source: {URL}"
    )

    # Include a short context snippet (left column text)
    snippet = "```\n" + (left_text[:1700] if left_text else "") + "\n```"
    payload = {"content": content + "\n" + snippet}

    r = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    r.raise_for_status()


# ----------------------- Main -----------------------
def main():
    tz = ZoneInfo(LOCAL_TZ)

    # Always use Playwright selectors here (site is JS/CSS structured).
    left_text, zones = fetch_next_tz_playwright()
    if DEBUG:
        print(f"[DEBUG] left_text present: {bool(left_text)}")
        if left_text:
            print("---- LEFT (Next Terror Zone) ----")
            print(left_text)
            print("------------- END --------------")
        print(f"[DEBUG] zones: {zones}")

    if not left_text:
        print("Could not locate the Next Terror Zone block — exiting.")
        return

    # Filter zones against watch list (case-insensitive)
    hits = [z for z in zones if z.lower() in WATCH_TERMS_LC]
    if DEBUG:
        print(f"[DEBUG] hits after filter: {hits}")
    if not hits:
        print("No watched terms in Next Terror Zone — exiting.")
        return

    start_dt_local = parse_next_timestamp(left_text, tz)
    if not start_dt_local:
        print("Could not parse timestamp; skipping send to avoid wrong times.")
        return

    now_local = datetime.now(tz)
    if should_send_now(now_local):
        print(f"Sending at {now_local.isoformat()} hits={hits} start={start_dt_local.isoformat()} force={FORCE}")
        send_webhook(hits, start_dt_local, left_text)
    else:
        print(f"Match present but not a send minute ({now_local.minute}). Skipping. force={FORCE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
