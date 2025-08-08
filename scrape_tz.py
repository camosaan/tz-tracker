import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import json
import pathlib

# Zones we care about
WATCHLIST = {"The Ancients' Way", "Icy Cellar"}

# Discord settings from GitHub secrets
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
ROLE_ID = os.environ["DISCORD_ROLE_ID"]

# Cache file location
CACHE_FILE = pathlib.Path("tz_alert_cache.json")

def load_cache():
    """Load the sent-alert cache from file."""
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}

def save_cache(data):
    """Save the sent-alert cache to file."""
    CACHE_FILE.write_text(json.dumps(data))

def delete_last_message(cache):
    """Delete the last Discord message sent by this script, if any."""
    last_id = cache.get("last_message_id")
    if not last_id:
        return

    # Extract webhook.id and webhook.token from WEBHOOK_URL
    try:
        parts = WEBHOOK_URL.strip("/").split("/")
        webhook_id = parts[-2]
        webhook_token = parts[-1]
    except Exception as e:
        print(f"Could not parse webhook URL for deletion: {e}")
        return

    delete_url = f"https://discord.com/api/webhooks/{webhook_id}/{webhook_token}/messages/{last_id}"
    try:
        resp = requests.delete(delete_url, timeout=10)
        if resp.status_code == 204:
            print(f"Deleted last message ID: {last_id}")
        else:
            print(f"Failed to delete message ID {last_id}, status: {resp.status_code}")
    except Exception as e:
        print(f"Error deleting last message: {e}")

def send_discord_message(message: str):
    """Send a message to Discord via webhook and return its message_id."""
    payload = {"content": message}
    resp = requests.post(WEBHOOK_URL, json=payload)
    resp.raise_for_status()
    data = resp.json()
    return data.get("id")

def get_next_zone():
    """Scrape the diablo2.io tracker page and return the Next zone name."""
    url = "https://diablo2.io/tzonetracker.php"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Find the table row containing the 'Next' label
    next_label = soup.find(string=lambda t: t and "Next" in t)
    if not next_label:
        return None

    next_row = next_label.find_parent("tr")
    if not next_row:
        return None

    # Get the zone name from the .z-bone span in that row
    zone_span = next_row.select_one(".z-bone")
    if zone_span:
        return zone_span.get_text(strip=True)
    return None

def next_hour_utc():
    """Return datetime for the top of the next hour in UTC."""
    now = datetime.now(timezone.utc)
    return (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))

def minutes_until(dt):
    """Return whole minutes until a datetime from now."""
    now = datetime.now(timezone.utc)
    return int((dt - now).total_seconds() // 60)

def main():
    cache = load_cache()

    zone = get_next_zone()
    if not zone:
        print("Could not find next zone.")
        return

    start_dt = next_hour_utc()
    mins = minutes_until(start_dt)
    epoch = int(start_dt.timestamp())

    # Local time for absolute display
    local_time_str = start_dt.astimezone().strftime("%-I:%M %p")

    print(f"Next zone: {zone}, starts at {start_dt.isoformat()} (~{mins} minutes)")

    force = os.environ.get("FORCE_DISCORD", "").lower() in ("1", "true", "yes")
    if zone not in WATCHLIST and not force:
        print("Zone not in watchlist.")
        return

    # Decide alert stage
    if mins >= 55:
        alert_stage = "60min"
    elif 25 <= mins <= 35:
        alert_stage = "30min"
    elif 0 < mins <= 7:
        alert_stage = "5min"
    else:
        alert_stage = "outside_window"

    cache_key = f"{zone}_{alert_stage}"

    if not force:
        if alert_stage == "outside_window":
            print("Not in an alert window.")
            return
        if cache.get(cache_key):
            print("Already alerted for this stage.")
            return
    else:
        print("FORCE_DISCORD flag set — sending alert regardless of window or cache.")

    # Delete the last message before sending a new one
    delete_last_message(cache)

    # Build fancy message with header + timing
    header_line = f"# ⚔️🔥 {zone} 🔥⚔️"
    timing_line = f"<@&{ROLE_ID}> up next <t:{epoch}:R> @ {local_time_str}"
    message = f"{header_line}\n{timing_line}"

    # Send the new message and store its ID
    message_id = send_discord_message(message)
    print(f"Sent alert (ID: {message_id}):\n{message}")

    cache[cache_key] = True
    cache["last_message_id"] = message_id
    save_cache(cache)

if __name__ == "__main__":
    main()
