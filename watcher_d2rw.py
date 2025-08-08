# watcher_d2rw.py
import os
import re
import requests
from datetime import datetime, timezone

URL = "https://d2runewizard.com/terror-zone-tracker"

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
ROLE_ID     = os.getenv("DISCORD_ROLE_ID", "").strip()
WATCH_TERMS = os.getenv("WATCH_TERMS", "Burial Grounds,Crypt,Mausoleum,Far Oasis")
WATCH = [t.strip() for t in WATCH_TERMS.split(",") if t.strip()]

DEBUG       = os.getenv("DEBUG", "false").lower() in {"1","true","yes"}
FORCE       = os.getenv("FORCE_SEND", "false").lower() in {"1","true","yes"}
TEST_PING   = os.getenv("TEST_PING", "false").lower() in {"1","true","yes"}

# minutes past the hour (UTC) when we allow sends
SEND_MINUTES = {5, 30, 45, 55}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36")
}

def should_send(now_utc: datetime) -> bool:
    return FORCE or (now_utc.minute in SEND_MINUTES)

def send_discord(message: str):
    payload = {
        "content": message,
        "allowed_mentions": {"roles": [ROLE_ID] if ROLE_ID else []},
    }
    r = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    if r.status_code >= 300:
        print(f"[WARN] Discord webhook {r.status_code}: {r.text[:300]}")
    else:
        print("[INFO] Discord message sent.")

def extract_next_block(html: str) -> str | None:
    """
    Grab everything from 'Next Terror Zone' up to either 'Current Terror Zone'
    or the end of the main content. Works even if tags/classes change.
    """
    m = re.search(
        r"(Next\s*Terror\s*Zone.*?)(?:Current\s*Terror\s*Zone|</main>|</body>|$)",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    return m.group(1)

def find_hits_in_block(block: str) -> list[str]:
    low = block.lower()
    hits = [w for w in WATCH if w.lower() in low]
    return sorted(set(hits), key=lambda x: low.find(x.lower()))

def main():
    if not WEBHOOK_URL:
        print("[CONFIG ERROR] DISCORD_WEBHOOK_URL is not set.")
        return

    if TEST_PING:
        mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""
        send_discord(f"{mention} Test ping from D2RW TZ Watcher ✅\n{URL}")
        print("[INFO] Sent TEST_PING and exiting.")
        return

    print("[DEBUG] Fetching page…")
    resp = requests.get(URL, headers=HEADERS, timeout=25)
    resp.raise_for_status()
    html = resp.text

    block = extract_next_block(html)
    if block is None:
        print("Error: Could not find the 'Next Terror Zone' block.")
        if DEBUG:
            print("[DEBUG] HTML preview:", html[:1200])
        return

    if DEBUG:
        preview = re.sub(r"\s+", " ", block)[:600]
        print(f"[DEBUG] Next block preview: {preview}")

    hits = find_hits_in_block(block)
    if not hits:
        print("No watched zones in Next Terror Zone — exiting.")
        return

    mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""
    when = "(time not provided on this page)"
    # If the page ever exposes a next timestamp later, we can add parsing here.

    now_utc = datetime.now(timezone.utc)
    if should_send(now_utc):
        send_discord(
            f"{mention} **Watched TZ detected!**\n"
            f"**Next zones:** {', '.join(hits)}\n"
            f"{when}\n"
            f"Source: {URL}"
        )
    else:
        print(f"Match found ({', '.join(hits)}) but not a send minute "
              f"({now_utc.minute}). FORCE={FORCE}")

if __name__ == "__main__":
    main()
