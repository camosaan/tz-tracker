import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

URL = "https://d2runewizard.com/terror-zone-tracker"

# Environment variables from GitHub
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
ROLE_ID     = os.getenv("DISCORD_ROLE_ID", "").strip()
WATCH_TERMS = os.getenv("WATCH_TERMS", "Burial Grounds,Crypt,Mausoleum,Far Oasis")
WATCH_SET   = {t.strip().lower() for t in WATCH_TERMS.split(",") if t.strip()}

DEBUG       = os.getenv("DEBUG", "false").lower() in {"1","true","yes"}
FORCE       = os.getenv("FORCE_SEND", "false").lower() in {"1","true","yes"}
TEST_PING   = os.getenv("TEST_PING", "false").lower() in {"1","true","yes"}

# Times in UTC minutes past the hour when we want to send
SEND_MINUTES = {5, 30, 45, 55}

def send_discord(message: str):
    payload = {
        "content": message,
        "allowed_mentions": {"roles": [ROLE_ID] if ROLE_ID else []}
    }
    r = requests.post(WEBHOOK_URL, json=payload)
    if r.status_code >= 300:
        print(f"[WARN] Discord webhook returned {r.status_code}: {r.text[:200]}")
    else:
        print("[INFO] Sent Discord message.")

def should_send(now_utc: datetime) -> bool:
    return FORCE or (now_utc.minute in SEND_MINUTES)

def get_next_zone():
    r = requests.get(URL, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Look for "Next Terror Zone" heading and get the list under it
    heading = soup.find("h3", string=lambda s: s and "Next Terror Zone" in s)
    if not heading:
        print("[ERROR] Could not find 'Next Terror Zone' heading.")
        return None

    # Find the list following the heading
    ul = heading.find_next("ul")
    if not ul:
        print("[ERROR] Could not find list of zones under Next Terror Zone.")
        return None

    zones = [li.get_text(strip=True) for li in ul.find_all("li")]
    return zones

def main():
    if not WEBHOOK_URL:
        print("[CONFIG ERROR] DISCORD_WEBHOOK_URL is not set.")
        return

    if TEST_PING:
        mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""
        send_discord(f"{mention} Test ping from D2RW TZ Watcher ✅\n{URL}")
        return

    zones = get_next_zone()
    if not zones:
        return

    if DEBUG:
        print(f"[DEBUG] Next Terror Zone list: {zones}")

    # Find any watched terms
    hits = [z for z in zones if z.lower() in WATCH_SET]
    if hits:
        mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""
        now_utc = datetime.now(timezone.utc)
        if should_send(now_utc):
            send_discord(
                f"{mention} **Watched TZ detected!**\n"
                f"**Zones:** {', '.join(hits)}\n"
                f"Source: {URL}"
            )
        else:
            print(f"Match found but not in send minute {now_utc.minute} (FORCE={FORCE})")
    else:
        print("No watched zones in Next Terror Zone.")

if __name__ == "__main__":
    main()
