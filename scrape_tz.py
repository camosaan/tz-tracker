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
    # Ensure JSON is returned (contains the message id)
    if "?" in WEBHOOK_URL:
        return WEBHOOK_URL if "wait=true" in WEBHOOK_URL else WEBHOOK_URL + "&wait=true"
    return WEBHOOK_URL + "?wait=true"

def webhook_base_url():
    # For deletes: no query string
    return WEBHOOK_URL.split("?")[0].rstrip("/")

def delete_last_message(cache):
    last_id = cache.get("last_message_id")
    if not last_id:
        return
    url = f"{webhook_base_url()}/messages/{last_id}"
    try:
        resp = requests.delete(url, timeout=10)
        if resp.status_code == 204:
            print(f"Deleted last message ID: {last_id}")
        else:
            print(f"Delete failed ({resp.status_code}): {resp.text[:200]}")
    except Exception as e:
        print(f"Error deleting last message: {e}")

def send_discord_message(message: str):
    resp = requests.post(webhook_url_with_wait(), json={"content": message}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("id")

# ----- Scraper -----
def get_next_zone():
    """Scrape the diablo2.io tracker page and return the 'Next' zone name."""
    url = "https://diablo2.io/tzonetracker.php"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Find the table row with the 'Next' label
    next_label = soup.find(string=lambda t: t and "Next" in t)
    if not next_label:
        return None
    next_row = next_label.find_parent("tr")
    if not next_row:
        return None

    span = next_row.select_one(".z-bone")
    return span.get_text(strip=True) if span else None

# ----- Time helpers -----
def next_hour_utc():
    now = datetime.now(timezone.utc)
    return (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))

def minutes_until(dt):
    now = datetime.now(timezone.utc)
    return int((dt - now).total_seconds() // 60)

# ----- Messaging -----
ZONE_THEME = {
    "Worldstone Keep": {"header": "⚔️🔥", "initial_tail": "Prepare yourselves for the onslaught"},
    "Chaos Sanctuary": {"header": "😈🔥", "initial_tail": "Diablo stirs..."},
    "The Secret Cow Level": {"header": "🐄🥛", "initial_tail": "Moooove fast — gates open soon"},
    "Cathedral": {"header": "🏰🕯️", "initial_tail": "Sanctify your gear"},
}

def build_message(zone: str, stage: str, epoch: int, local_time_str: str) -> str:
    theme = ZONE_THEME.get(zone, {"header": "⚔️🔥", "initial_tail": "Prepare yourselves"})
    h = theme["header"]
    header_line = f"# {h} {zone} {h}"

    if stage == "initial":
        timing_line = f"<@&{ROLE_ID}> **{zone}** up next! {theme['initial_tail']} @ {local_time_str}."
    elif stage == "30min":
        timing_line = f"<@&{ROLE_ID}> 30-minute warning! <t:{epoch}:R> @ {local_time_str}."
    elif stage == "15min":
        flavor = {
            "Worldstone Keep": "15 minutes to assemble!",
            "Chaos Sanctuary": "15 minutes until chaos reigns!",
            "The Secret Cow Level": "15 minutes until the herd is unleashed!",
            "Cathedral": "15 minutes until the bells toll!",
        }.get(zone, "15 minutes remaining!")
        timing_line = f"<@&{ROLE_ID}> {flavor} <t:{epoch}:R> @ {local_time_str}."
    else:  # stage == "5min"
        flavor = {
            "Worldstone Keep": "Final call — fight begins",
            "Chaos Sanctuary": "Final call — Diablo awaits",
            "The Secret Cow Level": "Final call — the pasture gates open",
            "Cathedral": "Final call — the bells will toll",
        }.get(zone, "Final call")
        timing_line = f"<@&{ROLE_ID}> {flavor} <t:{epoch}:R> @ {local_time_str}!"

    return f"{header_line}\n{timing_line}"

# ----- Stage logic -----
def determine_stage(mins_to_hour: int) -> str:
    """
    Map minutes-before-hour to checkpoints:
    :05 -> ~55 min  => 'initial'
    :30 -> ~30 min  => '30min'
    :45 -> ~15 min  => '15min'
    :55 -> ~5  min  => '5min'
    With a bit of slack.
    """
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

    # Flag: send every initial message as a demo (no scraping/windows/cache/deletes)
    send_all_initials = truthy_env("SEND_ALL_INITIALS")
    if send_all_initials:
        start_dt = next_hour_utc()
        epoch = int(start_dt.timestamp())
        try:
            local_time_str = start_dt.astimezone().strftime("%-I:%M %p")
        except ValueError:
            local_time_str = start_dt.astimezone().strftime("%#I:%M %p")

        print("SEND_ALL_INITIALS enabled — posting initial messages for all watchlist zones.")
        for zone in WATCHLIST:
            msg = build_message(zone, "initial", epoch, local_time_str)
            message_id = send_discord_message(msg)
            print(f"Posted demo initial for {zone} (ID: {message_id})")
        # Do NOT modify cache or delete anything in demo mode.
        return

    # Normal/forced flow
    zone = get_next_zone()
    if not zone:
        print("Could not find next zone.")
        return

    start_dt = next_hour_utc()
    mins = minutes_until(start_dt)
    epoch = int(start_dt.timestamp())
    try:
        local_time_str = start_dt.astimezone().strftime("%-I:%M %p")
    except ValueError:
        local_time_str = start_dt.astimezone().strftime("%#I:%M %p")

    print(f"Next zone: {zone}, starts at {start_dt.isoformat()} (~{mins} minutes)")

    force = truthy_env("FORCE_DISCORD")
    if zone not in WATCHLIST and not force:
        print("Zone not in watchlist.")
        return

    stage = determine_stage(mins)
    if not force and stage == "outside_window":
        print("Not at a scheduled checkpoint.")
        return

    cache_key = f"{zone}_{stage}"
    if not force and cache.get(cache_key):
        print("Already alerted for this stage.")
        return

    if force:
        print("FORCE_DISCORD set — sending alert regardless of window or cache.")

    # Delete previous message, then send the new one
    delete_last_message(cache)
    effective_stage = "initial" if (force and stage == "outside_window") else stage
    message = build_message(zone, effective_stage, epoch, local_time_str)
    message_id = send_discord_message(message)
    print(f"Sent alert (ID: {message_id}) for stage '{effective_stage}':\n{message}")

    cache[cache_key] = True
    cache["last_message_id"] = message_id
    save_cache(cache)

if __name__ == "__main__":
    main()
