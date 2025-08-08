import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import json
import pathlib
import time

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
    if "?" in WEBHOOK_URL:
        return WEBHOOK_URL if "wait=true" in WEBHOOK_URL else WEBHOOK_URL + "&wait=true"
    return WEBHOOK_URL + "?wait=true"

def webhook_base_url():
    return WEBHOOK_URL.split("?")[0].rstrip("/")

def delete_message_by_id(message_id: str) -> bool:
    if not message_id:
        return False
    url = f"{webhook_base_url()}/messages/{message_id}"
    try:
        resp = requests.delete(url, timeout=10)
        if resp.status_code == 204:
            return True
        return resp.status_code == 404  # treat not found as "deleted"
    except Exception:
        return False

def send_discord_message(message: str) -> str | None:
    resp = requests.post(webhook_url_with_wait(), json={"content": message}, timeout=15)
    resp.raise_for_status()
    return resp.json().get("id")

# ----- Scraper -----
def scrape_current_and_next(retries=2, delay=5):
    """Try scraping current/next, retry if next is None."""
    for attempt in range(retries + 1):
        current_zone, next_zone = _scrape_once()
        if next_zone:
            return current_zone, next_zone
        if attempt < retries:
            time.sleep(delay)
    return current_zone, next_zone

def _scrape_once():
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
    return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

def minutes_until(dt):
    now = datetime.now(timezone.utc)
    return int((dt - now).total_seconds() // 60)

# ----- Message builders -----
ZONE_THEME = {
    "Worldstone Keep": {"header": "⚔️🔥", "initial_tail": "Prepare yourselves for the onslaught"},
    "Chaos Sanctuary": {"header": "😈🔥", "initial_tail": "Diablo stirs..."},
    "The Secret Cow Level": {"header": "🐄🥛", "initial_tail": "Moooove fast — gates open soon"},
    "Cathedral": {"header": "🏰🕯️", "initial_tail": "Sanctify your gear"},
}
GENERIC_THEME = {"header": "⚔️🔥", "initial_tail": "Prepare yourselves"}

def build_info_message(current_zone, current_end_epoch, next_zone, next_start_epoch):
    header = "# 🕒 Terror Zone Status"
    cur_block = f"## ⏳ Current\n**{current_zone or 'TBD'}** — ends <t:{current_end_epoch}:R>"
    nxt_block = f"## 🔮 Next\n**{next_zone or 'TBD'}** — starts @ <t:{next_start_epoch}:t>"
    return f"{header}\n\n{cur_block}\n\n{nxt_block}"

def build_alert_message(zone, stage, epoch):
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

# ----- Stage logic -----
def determine_stage(mins_to_hour):
    if mins_to_hour >= 50:
        return "initial"
    if 26 <= mins_to_hour <= 35:
        return "30min"
    if 12 <= mins_to_hour <= 18:
        return "15min"
    if 3 <= mins_to_hour <= 7:
        return "5min"
    return None

# ----- Main -----
def main():
    cache = load_cache()

    # Scrape (with retry if next missing)
    current_zone, next_zone = scrape_current_and_next()

    next_start_dt = next_hour_utc()
    mins_to_next = minutes_until(next_start_dt)
    epoch_next = int(next_start_dt.timestamp())
    epoch_current_end = epoch_next

    print(f"Current: {current_zone} | Next: {next_zone} | {mins_to_next} mins to next")

    # --- INFO POST ---
    needs_info_update = (
        not cache.get("last_info_message_id")
        or cache.get("last_info_current_zone") != current_zone
        or cache.get("last_info_next_zone") != next_zone
    )

    if needs_info_update:
        if cache.get("last_info_message_id"):
            delete_message_by_id(cache["last_info_message_id"])
        info_msg = build_info_message(current_zone, epoch_current_end, next_zone, epoch_next)
        new_info_id = send_discord_message(info_msg)
        cache["last_info_message_id"] = new_info_id
        cache["last_info_current_zone"] = current_zone
        cache["last_info_next_zone"] = next_zone
        save_cache(cache)
        print(f"Info post updated (ID: {new_info_id})")

    # --- ALERTS ---
    stage = determine_stage(mins_to_next)
    if not stage:
        return

    if next_zone not in WATCHLIST:
        return

    cache_key = f"{next_zone}_{stage}"
    if cache.get(cache_key):
        return  # already sent this stage

    # delete last alert if exists
    if cache.get("last_alert_message_id"):
        delete_message_by_id(cache["last_alert_message_id"])

    alert_msg = build_alert_message(next_zone, stage, epoch_next)
    new_alert_id = send_discord_message(alert_msg)
    cache[cache_key] = True
    cache["last_alert_message_id"] = new_alert_id
    save_cache(cache)
    print(f"Alert sent for {next_zone} ({stage})")

if __name__ == "__main__":
    main()
