import os, re, sys
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

# ---------- Config via env ----------
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
ROLE_ID = os.environ["DISCORD_ROLE_ID"]  # role to mention
LOCAL_TZ = os.environ.get("LOCAL_TZ", "Europe/London")
DEBUG = os.environ.get("DEBUG", "0").lower() in {"1", "true", "yes"}
FORCE = os.environ.get("FORCE_SEND", "false").lower() in {"1", "true", "yes"}

DEFAULT_TERMS = ["Burial Grounds", "Crypt", "Mausoleum", "Far Oasis"]
WATCH_TERMS = [t.strip() for t in os.environ.get("WATCH_TERMS", ",".join(DEFAULT_TERMS)).split(",") if t.strip()]
WATCH_TERMS_LC = {t.lower() for t in WATCH_TERMS}

# Send at these local minutes: :05 (initial), then :30, :45, :55
SEND_MINUTES = {5, 30, 45, 55}

URL = "https://d2emu.com/tz"


# ---------- Playwright extraction (robust) ----------
def fetch_next_tz_playwright() -> tuple[str | None, list[str]]:
    """
    Find a container that contains the text 'Next Terror Zone' AND at least one UL>LI>A link.
    Return (container_text, [zone names]).
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")),
        page = page[0]  # new_page returns a tuple in some wrappers; take the first

        # Be a little more “browser-like”
        page.set_extra_http_headers({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        })
        page.set_default_timeout(30000)
        page.goto(URL, wait_until="load")
        page.wait_for_timeout(2000)  # small settle time

        # How many anchors exist?
        try:
            anchor_count = page.locator("text=Next Terror Zone").count()
        except Exception:
            anchor_count = 0
        if DEBUG:
            print(f"[DEBUG] anchors with 'Next Terror Zone': {anchor_count}")

        # Choose any DIV that has the text *and* has UL LI A links inside
        container = page.locator("css=div", has_text="Next Terror Zone").filter(
            has=page.locator("css=ul li a")
        ).first

        try:
            container.wait_for(state="attached", timeout=6000)
        except PWTimeout:
            if DEBUG:
                # Give us something to diagnose
                try:
                    body_text = page.locator("body").inner_text()[:700]
                except Exception:
                    body_text = "<no body text>"
                print("[DEBUG] No suitable container; body preview:")
                print(body_text)
            browser.close()
            return None, []

        # Full text of the container (for timestamp parsing)
        try:
            block_text = container.inner_text().strip()
        except Exception:
            block_text = ""

        # All zone names (links) in that same container
        try:
            zones = [t.strip() for t in container.locator("css=ul li a").all_inner_texts() if t.strip()]
        except Exception:
            zones = []

        if DEBUG:
            print("[DEBUG] block snippet >>>")
            print(block_text[:700])
            print("<<< block snippet end")
            print(f"[DEBUG] zones: {zones}")

        browser.close()
        return (block_text if block_text else None), zones


# ---------- helpers ----------
def parse_next_timestamp(block_text: str, tz: ZoneInfo) -> datetime | None:
    """
    Extract 'DD/MM/YYYY, HH:MM:SS' or 'M/D/YYYY, HH:MM:SS' from the text and attach tz.
    """
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2}:\d{2})", block_text or "")
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


def send_webhook(zones: list[str], start_dt_local: datetime, context_text: str):
    # Discord auto-localized time tags
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
    snippet = "```\n" + (context_text[:1700] if context_text else "") + "\n```"

    r = requests.post(WEBHOOK_URL, json={"content": content + "\n" + snippet}, timeout=20)
    r.raise_for_status()


# ---------- main ----------
def main():
    tz = ZoneInfo(LOCAL_TZ)

    block_text, zones = fetch_next_tz_playwright()
    if DEBUG:
        print(f"[DEBUG] block_text present: {bool(block_text)}")

    if not block_text:
        print("Could not locate the Next Terror Zone block — exiting.")
        return

    # Filter for watched zones (case-insensitive)
    hits = [z for z in zones if z.lower() in WATCH_TERMS_LC]
    if DEBUG:
        print(f"[DEBUG] hits after filter: {hits}")

    if not hits:
        print("No watched terms in Next Terror Zone — exiting.")
        return

    start_dt_local = parse_next_timestamp(block_text, tz)
    if not start_dt_local:
        print("Could not parse timestamp; skipping send to avoid wrong times.")
        return

    now_local = datetime.now(tz)
    if should_send_now(now_local):
        print(f"Sending at {now_local.isoformat()} hits={hits} start={start_dt_local.isoformat()} force={FORCE}")
        send_webhook(hits, start_dt_local, block_text)
    else:
        print(f"Match present but not a send minute ({now_local.minute}). Skipping. force={FORCE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
