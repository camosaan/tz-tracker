import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import json
import pathlib

# ----- Config -----
WATCHLIST = {
    "Worldstone Keep",
    "Chaos Sanctuary",
    "The Secret Cow Level",
    "Cathedral",
}

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].strip()
ROLE_ID = os.environ["DISCORD_ROLE_ID"]

CACHE_FILE = pathlib.Path("tz_alert_cache.json")

# ----- Cache helpers -----
def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}

def save_cache(data):
    CACHE_FILE.write_text(json.dumps(data))

# ----- Discord helpers -----
def webhook_url_with_wait():
    # Ensure we get JSON back (message id) by using ?wait=true
    if "?" in WEBHOOK_URL:
        return WEBHOOK_URL if "wait=true" in WEBHOOK_URL else WEBHOOK_URL + "&wait=true"
    return WEBHOOK_URL + "?wait=true"

def webhook_base_url():
    # For deletes: strip querystring
    return WEBHOOK_URL.split("?")[0].rstrip("/")

def delete_message_by_id(message_id: str) -> bool:
    """Delete a specific webhook message. Returns True if deleted or already gone (404)."""
    if not message_id:
        return False
    url = f"{webhook_base_url()}/messages/{message_id}"
    try:
        resp = requests.delete(url, timeout=10)
        if resp.status_code == 204:
            print(f"Deleted message ID: {message_id}")
            return True
        else:
            # 404 means it's already gone (manual delete etc.) — treat as success
            print(f"Delete failed ({resp.status_code}): {resp.text[:200]}")
            return resp.status_code == 404
    except Exception as e:
        print(f"Error deleting message: {e}")
        return False

def send_discord_message(message: str) -> str | None:
    """Send a message and return its id (requires ?wait=true)."""
    resp = requests.post(webhook_url_with_wait(), json={"content": message}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("id")

# ----- Scraper -----
def get_current_and_next():
    """Return (current_zone, next_zone) from diablo2.io tracker."""
    url = "https://diablo2.io/tzonetracker.php"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    cur_label = soup.find(string=lambda t: t and "Current" in t)
    nxt_label = soup.find(string=lambda t: t and "Next" in t)

    current_zone, next_zone = None, None

    if cur_label:
        cur_row = cur_label.find_parent("tr")
        if cur_row:
            span = cur_row.select_one(".z-bone")
            if span:
                current_zone = span.get_text(strip=True)

    if nxt_label:
        nxt_row = nxt_label.find_parent("tr")
        if nxt_row:
            span = nxt_row.select_one(".z-bone")
            if span:
                next_zone = span.get_text(strip=True)

    return current_zone, next_zone

# ----- Time helpers -----
def next_hour_utc():
    now = datetime.now(timezone.utc)
    return (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))

def minutes_until(dt):
    now = datetime.now(timezone.utc)
    return int((dt - now).total_seconds() // 60)

# ----- Messaging (alerts) -----
ZONE_THEME = {
    "Worldstone Keep": {"header": "⚔️🔥", "initial_tail": "Prepare yourselves for the onslaught"},
    "Chaos Sanctuary": {"header": "😈🔥", "initial_tail": "Diablo stirs..."},
    "The Secret Cow Level": {"header": "🐄🥛", "initial_tail": "Moooove fast — gates open soon"},
    "Cathedral": {"header": "🏰🕯️", "initial_tail": "Sanctify your gear"},
}
GENERIC_THEME = {"header": "⚔️🔥", "initial_tail": "Prepare yourselves"}

def build_alert_message(zone: str, stage: str, epoch: int) -> str:
    """
    Two-line alert:
      Line 1: H1 header with themed emojis + zone name
      Line 2: Role ping + stage text + Discord relative/absolute time
    """
    theme = ZONE_THEME.get(zone, GENERIC_THEME)
    h = theme["header"]
    header_line = f"# {h} {zone} {h}"

    if stage == "initial":
        timing_line = f"<@&{ROLE_ID}> **{zone}** up next! {theme['initial_tail']} @ <t:{epoch}:t>."
    elif stage == "30min":
        timing_line = f"<@&{ROLE_ID}> 30-minute warning! <t:{epoch}:R> @ <t:{epoch}:t>."
    elif stage == "15min":
        flavor = {
            "Worldstone Keep": "15 minutes to assemble!",
            "Chaos Sanctuary": "15 minutes until chaos reigns!",
            "The Secret Cow Level": "15 minutes until the herd is unleashed!",
            "Cathedral": "15 minutes until the bells toll!",
        }.get(zone, "15 minutes remaining!")
        timing_line = f"<@&{ROLE_ID}> {flavor} <t:{epoch}:R> @ <t:{epoch}:t>."
    else:  # 5min
        flavor = {
            "Worldstone Keep": "Final call — fight begins",
            "Chaos Sanctuary": "Final call — Diablo awaits",
            "The Secret Cow Level": "Final call — the pasture gates open",
            "Cathedral": "Final call — the bells will toll",
        }.get(zone, "Final call")
        timing_line = f"<@&{ROLE_ID}> {flavor} <t:{epoch}:R> @ <t:{epoch}:t>!"

    return f"{header_line}\n{timing_line}"

# ----- Messaging (info post) -----
def build_info_message(current_zone: str | None, current_end_epoch: int, next_zone: str | None, next_start_epoch: int) -> str:
    """
    Big title, then distinct sections with icons:
    - ⏳ Current: bold zone name + relative countdown
    - 🔮 Next: bold zone name + absolute time
    """
    header = "# 🕒 Terror Zone Status"
    cur_block = f"## ⏳ Current\n**{current_zone or 'Unknown'}** — ends <t:{current_end_epoch}:R>"
    nxt_block = f"## 🔮 Next\n**{next_zone or 'Unknown'}** — starts @ <t:{next_start_epoch}:t>"
    return f"{header}\n\n{cur_block}\n\n{nxt_block}"

# ----- Stage logic -----
def determine_stage(mins_to_hour: int) -> str:
    # :05 (~55m), :30 (~30m), :45 (~15m), :55 (~5m)
    if mins_to_hour >= 50:
        return "initial"
    if 26 <= mins_to_hour <= 35:
        return "30min"
    if 12 <= mins_to_hour <= 18:
        return "15min"
    if 3 <= mins_to_hour <= 7:
        return "5min"
    return "outside_window"

def truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")

# ----- Main -----
def main():
    cache = load_cache()

    # Demo mode: post initial alerts for ALL watchlist zones (no deletes/cache/windows)
    if truthy_env("SEND_ALL_INITIALS"):
        start_dt = next_hour_utc()
        epoch = int(start_dt.timestamp())
        print("SEND_ALL_INITIALS enabled — posting initial messages for all watchlist zones.")
        for zone in WATCHLIST:
            msg = build_alert_message(zone, "initial", epoch)
            message_id = send_discord_message(msg)
            print(f"Posted demo initial for {zone} (ID: {message_id})")
        return

    # Scrape both Current and Next
    current_zone, next_zone = get_current_and_next()
    if not next_zone and not current_zone:
        print("Could not find current/next zones.")
        return

    next_start_dt = next_hour_utc()
    mins_to_next = minutes_until(next_start_dt)
    epoch_next = int(next_start_dt.timestamp())
    epoch_current_end = epoch_next  # current ends when next starts

    print(f"Current: {current_zone or 'Unknown'} | Next: {next_zone or 'Unknown'} "
          f"| Next starts at {next_start_dt.isoformat()} (~{mins_to_next} minutes)")

    force = truthy_env("FORCE_DISCORD")

    # ===== INFO POST (recover/update every run if missing/changed) =====
    needs_info_update = (
        not cache.get("last_info_message_id")
        or cache.get("last_info_current_zone") != current_zone
        or cache.get("last_info_next_zone") != next_zone
    )

    if needs_info_update:
        info_msg = build_info_message(current_zone, epoch_current_end, next_zone, epoch_next)
        if cache.get("last_info_message_id"):
            if delete_message_by_id(cache["last_info_message_id"]):
                cache["last_info_message_id"] = None
        new_info_id = send_discord_message(info_msg)
        print(f"Posted/Updated info status (ID: {new_info_id})")
        cache["last_info_message_id"] = new_info_id
        cache["last_info_current_zone"] = current_zone
        cache["last_info_next_zone"] = next_zone
        save_cache(cache)

    # ===== ALERTS =====
    stage = determine_stage(mins_to_next)

    # At :05, if next not in watchlist, delete last alert & skip
    if not force and next_zone not in WATCHLIST and stage == "initial":
        print("Next zone not in watchlist at :05 — deleting last alert and skipping pings.")
        last_alert_id = cache.get("last_alert_message_id")
        if last_alert_id:
            if delete_message_by_id(last_alert_id):
                cache["last_alert_message_id"] = None
                save_cache(cache)
        return

    if not force and stage == "outside_window":
        print("Not at a scheduled alert checkpoint.")
        return

    if next_zone not in WATCHLIST and not force:
        print("Next zone not in watchlist — no alert.")
        return

    cache_key = f"{(next_zone or 'Unknown')}_{stage}"
    if not force and cache.get(cache_key):
        print("Already alerted for this stage.")
        return

    if force:
        print("FORCE_DISCORD set — sending alert regardless of window or cache.")

    # Replace the previous alert message
    last_alert_id = cache.get("last_alert_message_id")
    if last_alert_id:
        if delete_message_by_id(last_alert_id):
            cache["last_alert_message_id"] = None
            save_cache(cache)

    effective_stage = "initial" if (force and stage == "outside_window") else stage
    alert_msg = build_alert_message(next_zone or "Unknown", effective_stage, epoch_next)
    new_alert_id = send_discord_message(alert_msg)
    print(f"Sent alert (ID: {new_alert_id}) for stage '{effective_stage}':\n{alert_msg}")

    cache[cache_key] = True
    cache["last_alert_message_id"] = new_alert_id
    save_cache(cache)

if __name__ == "__main__":
    main()
