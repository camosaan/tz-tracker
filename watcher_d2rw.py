import os
import re
import requests
from datetime import datetime, timezone

URL = "https://d2runewizard.com/terror-zone-tracker"

# --- Discord / config ---
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
ROLE_ID     = os.getenv("DISCORD_ROLE_ID", "").strip()

# If you want to override in repo vars, set WATCH_TERMS there.
# Otherwise we default to your shortlist here.
DEFAULT_WATCH = "Chaos Sanctuary,Worldstone Keep,World Stone Keep,Catacombs,Secret Cow Level,Cow Level,Cows"
WATCH_TERMS = os.getenv("WATCH_TERMS", DEFAULT_WATCH)
WATCH = [w.strip() for w in WATCH_TERMS.split(",") if w.strip()]

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

    # Find the "Next Terror Zone" heading, then scan forward from there
    idx_next = html.lower().find("next terror zone")
    if idx_next == -1:
        print("Error: Could not find the 'Next Terror Zone' text.")
        if DEBUG:
            print("[DEBUG] HTML preview:", html[:1000])
        return

    # Take a generous forward slice (names should be in here)
    forward = html[idx_next: idx_next + 50000]  # plenty of room
    if DEBUG:
        prev = re.sub(r"\s+", " ", forward[:800])
        print(f"[DEBUG] Next-section preview: {prev}")

    # Look for any watch term inside this forward slice
    low = forward.lower()
    hits = []
    for term in WATCH:
        if term.lower() in low:
            hits.append(term)

    # Deduplicate but keep order of first appearance
    seen = set()
    hits = [h for h in hits if not (h.lower() in seen or seen.add(h.lower()))]

    if not hits:
        print("No watched zones in Next Terror Zone — exiting.")
        return

    # Compact variants: if both Worldstone Keep and World Stone Keep matched, show once
    canonical_map = {
        "worldstone keep": "Worldstone Keep",
        "world stone keep": "Worldstone Keep",
        "secret cow level": "Secret Cow Level",
        "cow level": "Secret Cow Level",
        "cows": "Secret Cow Level",
    }
    display_hits = []
    used = set()
    for h in hits:
        key = canonical_map.get(h.lower(), h)
        key_l = key.lower()
        if key_l not in used:
            used.add(key_l)
            display_hits.append(key)

    mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""
    now_utc = datetime.now(timezone.utc)

    if should_send(now_utc):
        send_discord(
            f"{mention} **Watched TZ detected (NEXT):** {', '.join(display_hits)}\n"
            f"Source: {URL}"
        )
    else:
        print(f"Match found ({', '.join(display_hits)}) but not a send minute "
              f"({now_utc.minute}). FORCE={FORCE}")

if __name__ == "__main__":
    main()
