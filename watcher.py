import os, re, sys
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
ROLE_ID = os.environ["DISCORD_ROLE_ID"]

# Your local tz (used only to format the Discord timestamps cleanly)
LOCAL_TZ = os.environ.get("LOCAL_TZ", "Europe/London")

# Comma-separated list in env overrides defaults
_default_terms = ["Burial Grounds", "Crypt", "Mausoleum", "Far Oasis"]
WATCH_TERMS = [t.strip() for t in os.environ.get("WATCH_TERMS", ",".join(_default_terms)).split(",") if t.strip()]
WATCH_TERMS_SET = {t.lower() for t in WATCH_TERMS}

# Minutes we actually send at (initial detect @ :05, then 30/15/5 before top of hour)
SEND_MINUTES = {5, 30, 45, 55}

URL = "https://d2emu.com/tz"

def fetch_page() -> str:
    r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.raise_for_status()
    return r.text

def get_next_section_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    m = re.search(r"(Next\s*Terror\s*Zone:.*?)(Current\s*Terror\s*Zone:|$)", text, re.I | re.S)
    section = (m.group(1) if m else text).strip()
    section = re.sub(r"[ \t]+", " ", section)
    section = re.sub(r"\n+", "\n", section)
    return section

def parse_next_timestamp(section: str, tz: ZoneInfo) -> datetime | None:
    m = re.search(r"(\d{2}/\d{2}/\d{4}),\s*(\d{2}:\d{2}:\d{2})", section)
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

def find_hits(section: str) -> list[str]:
    low = section.lower()
    hits = [t for t in WATCH_TERMS if t.lower() in low]
    # preserve original capitalization from WATCH_TERMS for display
    return sorted(hits, key=lambda s: s.lower())

def should_send_now(now_local: datetime, force: bool) -> bool:
    if force:
        return True
    return now_local.minute in SEND_MINUTES

def send_webhook(zones: list[str], start_dt_local: datetime, section: str):
    # Discord timestamps (auto-localize for everyone)
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
    snippet = "```\n" + section[:1700] + "\n```"
    payload = {"content": content + "\n" + snippet}

    r = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    r.raise_for_status()

def main():
    force = os.environ.get("FORCE_SEND", "").lower() in {"1", "true", "yes"}
    try:
        html = fetch_page()
        section = get_next_section_text(html)
        hits = find_hits(section)
        if not hits:
            print("No watched terms in Next Terror Zone — exiting.")
            return

        tz = ZoneInfo(LOCAL_TZ)
        start_dt_local = parse_next_timestamp(section, tz)
        if start_dt_local is None:
            print("Could not parse timestamp; skipping send to avoid wrong times.")
            return

        now_local = datetime.now(tz)
        if should_send_now(now_local, force):
            print(f"Sending at {now_local.isoformat()} hits={hits} start={start_dt_local.isoformat()} force={force}")
            send_webhook(hits, start_dt_local, section)
        else:
            print(f"Match present but not a send minute ({now_local.minute}). Skipping. force={force}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise

if __name__ == "__main__":
    main()
