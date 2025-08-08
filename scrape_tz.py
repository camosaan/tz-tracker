import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import json
import pathlib

WATCHLIST = {"The Ancients' Way", "Icy Cellar"}
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
ROLE_ID = os.environ["DISCORD_ROLE_ID"]

CACHE_FILE = pathlib.Path("tz_alert_cache.json")

def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}

def save_cache(data):
    CACHE_FILE.write_text(json.dumps(data))

def send_discord_message(message: str):
    payload = {"content": message}
    resp = requests.post(WEBHOOK_URL, json=payload)
    resp.raise_for_status()

def get_next_zone():
    url = "https://d2emu.com/terrorzone"  # replace with actual tracker URL
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Find the table row with "Next" label
    next_label = soup.find(string=lambda t: t and "Next" in t)
    if not next_label:
        return None

    next_row = next_label.find_parent("tr")
    if not next_row:
        return None

    zone_span = next_row.select_one(".z-bone")
    if zone_span:
        return zone_span.get_text(strip=True)
    return None

def minutes_until_next_hour():
    now = datetime.now(timezone.utc)
    next_hour = (now.replace(minute=0, second=0, microsecond=0) 
                 + timedelta(hours=1))
    return int((next_hour - now).total_seconds() // 60)

def main():
    cache = load_cache()

    zone = get_next_zone()
    if not zone:
        print("Could not find next zone.")
        return

    mins = minutes_until_next_hour()
    print(f"Next zone: {zone}, starts in {mins} minutes")

    if zone not in WATCHLIST:
        print("Zone not in watchlist.")
        return

    if mins >= 55:
        alert_stage = "60min"
    elif 25 <= mins <= 35:
        alert_stage = "30min"
    elif 0 < mins <= 7:
        alert_stage = "5min"
    else:
        return  # Not in alert window

    cache_key = f"{zone}_{alert_stage}"
    if cache.get(cache_key):
        print("Already alerted for this stage.")
        return

    message = f"<@&{ROLE_ID}> {zone} up next in {alert_stage.replace('min',' minutes')}!"
    send_discord_message(message)
    print(f"Sent alert: {message}")

    cache[cache_key] = True
    save_cache(cache)

if __name__ == "__main__":
    main()
