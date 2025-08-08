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

def send_discord_message(message: str):
    """Send a message to Discord via webhook."""
    payload = {"content": message}
    resp = requests.post(WEBHOOK_URL, json=payload)
    resp.raise_for_status()

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

    # Build message with bold zone name and Discord timestamps
    message = (
        f"<@&{ROLE_ID}> **{zone}** up next <t:{epoch}:R> "
        f"(at <t:{epoch}:t>)."
    )

    send_discord_message(message)
    print(f"Sent alert: {message}")

    cache[cache_key] = True
    save_cache(cache)

if __name__ == "__main__":
    main()
