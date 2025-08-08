import os, re, requests
from datetime import datetime, timezone

URL = "https://d2runewizard.com/terror-zone-tracker"

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
ROLE_ID     = os.getenv("DISCORD_ROLE_ID", "").strip()

DEFAULT_WATCH = "Chaos Sanctuary,Worldstone Keep,World Stone Keep,Catacombs,Secret Cow Level,Cow Level,Cows"
WATCH_TERMS = os.getenv("WATCH_TERMS", DEFAULT_WATCH)
WATCH = [w.strip() for w in WATCH_TERMS.split(",") if w.strip()]

DEBUG       = os.getenv("DEBUG", "false").lower() in {"1","true","yes"}
FORCE       = os.getenv("FORCE_SEND", "false").lower() in {"1","true","yes"}
TEST_PING   = os.getenv("TEST_PING", "false").lower() in {"1","true","yes"}

SEND_MINUTES = {5, 30, 45, 55}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36")
}

# Known zone names so we can *display* what we found in the NEXT block
KNOWN_ZONES = [
    "Blood Moor","Den of Evil","Cold Plains","Burial Grounds","Crypt","Mausoleum",
    "Stony Field","Tristram","Dark Wood","Black Marsh","Tower Cellar","Barracks",
    "Jail","Inner Cloister","Cathedral","Catacombs","Pit","Tamoe Highland",
    "Sewers","Rocky Waste","Dry Hills","Halls of the Dead","Far Oasis","Maggot Lair",
    "Lost City","Valley of Snakes","Claw Viper Temple","Stony Tomb","Ancient Tunnels",
    "Arcane Sanctuary",
    "Spider Forest","Arachnid Lair","Great Marsh","Flayer Jungle","Flayer Dungeon",
    "Kurast Bazaar","Ruined Temple","Disused Fane","Upper Kurast","Travincal",
    "Durance of Hate",
    "Outer Steppes","Plains of Despair","City of the Damned","River of Flame","Chaos Sanctuary",
    "Bloody Foothills","Frigid Highlands","Abaddon","Arreat Plateau","Pit of Acheron",
    "Crystalline Passage","Frozen River","Glacial Trail","Drifter Cavern","Frozen Tundra",
    "Infernal Pit","Ancient's Way","Icy Cellar","Worldstone Keep","Throne of Destruction",
    "Secret Cow Level","Cow Level","Cows"
]

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

def slice_next_block(html: str) -> str | None:
    """Return HTML slice that corresponds to the *Next* TZ card content."""
    i = html.lower().find("next terror zone")
    if i == -1:
        return None
    # take a forward window; the zone names are rendered just after the timer block
    # stop at the next H2/H3 (start of another card) if any
    fwd = html[i:i+120000]  # generous
    m = re.search(r"</h[23]>", fwd, flags=re.IGNORECASE)
    start = m.end() if m else 0
    # cut until the next heading/card boundary
    m2 = re.search(r"<h[23][^>]*>", fwd[start:], flags=re.IGNORECASE)
    end = start + m2.start() if m2 else len(fwd)
    return fwd[start:end]

def find_names(block: str, names: list[str]) -> list[str]:
    low = block.lower()
    found = [n for n in names if n.lower() in low]
    # keep first-seen order & dedupe
    seen = set()
    out = []
    for n in found:
        k = n.lower()
        if k not in seen:
            seen.add(k)
            out.append(n)
    return out

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

    block = slice_next_block(html)
    if not block:
        print("Error: Could not isolate the Next Terror Zone block.")
        if DEBUG:
            print("[DEBUG] HTML preview:", html[:1200])
        return

    if DEBUG:
        prev = re.sub(r"\s+", " ", block)[:800]
        print(f"[DEBUG] Next block preview: {prev}")

    # Show what we believe the NEXT zones are (for sanity)
    discovered = find_names(block, KNOWN_ZONES)
    if discovered:
        print("[INFO] Parsed NEXT zones:", ", ".join(discovered))

    # Only alert if one of YOUR watch terms is present
    hits = find_names(block, WATCH)
    if not hits:
        print("No watched zones in Next Terror Zone — exiting.")
        return

    # Normalize a couple of variants for display (doesn't change matching)
    canonical = {
        "world stone keep": "Worldstone Keep",
        "worldstone keep": "Worldstone Keep",
        "cow level": "Secret Cow Level",
        "cows": "Secret Cow Level",
    }
    display = []
    seen = set()
    for h in hits:
        c = canonical.get(h.lower(), h)
        if c.lower() not in seen:
            seen.add(c.lower())
            display.append(c)

    mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""
    now_utc = datetime.now(timezone.utc)
    if should_send(now_utc):
        send_discord(
            f"{mention} **Watched TZ detected (NEXT):** {', '.join(display)}\n"
            f"Source: {URL}"
        )
    else:
        print(f"Match found ({', '.join(display)}) but not a send minute "
              f"({now_utc.minute}). FORCE={FORCE}")

if __name__ == "__main__":
    main()
