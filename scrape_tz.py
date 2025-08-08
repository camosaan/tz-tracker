#!/usr/bin/env python3
import os
import json
import requests
import datetime
from datetime import timezone, timedelta
from pathlib import Path

# === Config from environment ===
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
ROLE_ID = os.getenv("DISCORD_ROLE_ID")

FORCE_DISCORD = os.getenv("FORCE_DISCORD", "").lower() == "true"
SEND_ALL_INITIALS = os.getenv("SEND_ALL_INITIALS", "").lower() == "true"

TARGET_MINUTES = {int(x) for x in os.getenv("TARGET_MINUTES", "5,30,45,55").split(",")}
WINDOW_MINUTES = int(os.getenv("WINDOW_MINUTES", "4"))

CACHE_FILE = Path("tz_alert_cache.json")

# === Step 1: Check if we're inside the target window ===
now = datetime.datetime.now(timezone.utc)
minute = now.minute

within_window = any(
    (minute - t) % 60 <= WINDOW_MINUTES or (t - minute) % 60 <= WINDOW_MINUTES
    for t in TARGET_MINUTES
)

if not within_window and not FORCE_DISCORD:
    print(f"[{now.isoformat()}] Outside target window; skipping run.")
    exit(0)

# === Step 2: Load cache ===
if CACHE_FILE.exists():
    with open(CACHE_FILE, "r") as f:
        cache = json.load(f)
else:
    cache = {}

# Example cache structure:
# { "last_posted_zone": "Zone Name", "last_post_time": "2025-08-08T05:30:00Z" }

# === Step 3: Scrape Terror Zone data ===
# Replace this with your actual scraping logic
def scrape_terror_zone():
    # Placeholder example — replace with real request/parse
    zone_name = "Bloody Foothills"
    zone_end_time = now + timedelta(minutes=60)  # Example
    return zone_name, zone_end_time

zone, end_time = scrape_terror_zone()

# === Step 4: Avoid duplicate posting in same window ===
last_zone = cache.get("last_posted_zone")
last_post_time_str = cache.get("last_post_time")
last_post_time = (
    datetime.datetime.fromisoformat(last_post_time_str.replace("Z", "+00:00"))
    if last_post_time_str else None
)

already_posted = (
    last_zone == zone and
    last_post_time and
    (now - last_post_time) < timedelta(minutes=WINDOW_MINUTES)
)

if already_posted and not FORCE_DISCORD:
    print(f"[{now.isoformat()}] Already posted zone '{zone}' in this window; skipping.")
    exit(0)

# === Step 5: Send to Discord ===
content = f"<@&{ROLE_ID}> Terror Zone: **{zone}** until {end_time.strftime('%H:%M UTC')}"
payload = {"content": content}

if WEBHOOK_URL:
    resp = requests.post(WEBHOOK_URL, json=payload)
    if resp.status_code == 204:
        print(f"[{now.isoformat()}] Posted to Discord: {zone}")
    else:
        print(f"[{now.isoformat()}] Discord webhook failed: {resp.status_code} {resp.text}")
else:
    print("No DISCORD_WEBHOOK_URL set; printing instead:")
    print(content)

# === Step 6: Update cache ===
cache["last_posted_zone"] = zone
cache["last_post_time"] = now.replace(microsecond=0).isoformat() + "Z"

with open(CACHE_FILE, "w") as f:
    json.dump(cache, f, indent=2)
