import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+
import requests
from bs4 import BeautifulSoup

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
ROLE_ID = os.environ["DISCORD_ROLE_ID"]
LOCAL_TZ = os.environ.get("LOCAL_TZ", "UTC")  # e.g., "Europe/London"

WATCH_TERMS = {"burial grounds", "crypt", "mausoleum"}  # lowercase for compare
SEND_MINUTES = {5, 30, 45, 55}  # :05 detection, and 30/15/5 before top-of-hour

URL = "https://d2emu.com/tz"

def get_next_section_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    # Capture "Next Terror Zone: ... (until next labeled section or end)"
    m = re.search(r"(Next\s*Terror\s*Zone:.*?)(Current\s*Terror\s*Zone:|$)", text, re.I | re.S)
    section = (m.group(1) if m else text).strip()
    # Normalize spacing a bit
    section = re.sub(r"[ \t]+", " ", section)
    section = re.sub(r"\n+", "\n", section)
    return section

def has_watch_terms(section: str) -> list[str]:
    lower = section.lower()
    hits = [t for t in WATCH_TERMS if t in lower]
    return sorted(hits)

def fetch_page() -> str:
    resp = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    resp.raise_for_status()
    return resp.text

def should_send_now(now_local: datetime) -> bool:
    return now_local.minute in SEND_MINUTES

def send_webhook(hits: list[str], section: str):
    mention = f"<@&{ROLE_ID}>"
    content = (
        f"{mention} **Terror Zone match detected**\n"
        f"Matched: {', '.join(h.title() for h in hits)}\n"
        f"Source: {URL}\n"
    )
    # Keep it short (Discord has limits); include section snippet for context.
    snippet = "```\n" + section[:1700] + "\n```"
    data = {"content": content + snippet}
    r = requests.post(WEBHOOK_URL, json=data, timeout=20)
    r.raise_for_status()

def main():
    try:
        html = fetch_page()
        section = get_next_section_text(html)
        hits = has_watch_terms(section)
        if not hits:
            print("No watched terms in Next Terror Zone — exiting.")
            return

        now_local = datetime.now(ZoneInfo(LOCAL_TZ))
        if should_send_now(now_local):
            print(f"Sending at {now_local.isoformat()} for hits={hits}")
            send_webhook(hits, section)
        else:
            print(f"Match present but not a send minute ({now_local.minute}). Skipping.")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        # Don't crash the workflow; just exit non-zero so it's visible in logs.
        raise

if __name__ == "__main__":
    main()
