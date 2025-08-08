#!/usr/bin/env python3
import os, re, json, time, urllib.request

DEBUG        = os.getenv("DEBUG", "false").lower() == "true"
DISCORD_URL  = os.getenv("DISCORD_WEBHOOK_URL")
DISCORD_ROLE = os.getenv("DISCORD_ROLE_ID", "")
WATCH_TERMS  = [t.strip().lower() for t in os.getenv("WATCH_TERMS", "").split(",") if t.strip()]
FORCE_SEND   = os.getenv("FORCE_SEND", "false").lower() == "true"
TEST_PING    = os.getenv("TEST_PING", "false").lower() == "true"

TARGET_URL   = "https://d2runewizard.com/terror-zone-tracker"
CUR_MARKER   = "Current Terror Zone"
NEXT_MARKER  = "Next Terror Zone"

STATE_FILE   = ".last_zone_d2rw.json"

def log(*a):
    if DEBUG:
        print("[DEBUG]", *a)

def fetch(url: str) -> str:
    log("Fetching:", url)
    with urllib.request.urlopen(url, timeout=20) as r:
        html = r.read().decode("utf-8", "ignore")
    log("Got HTML length:", len(html))
    return html

def normalize_text(html: str) -> str:
    txt = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    txt = re.sub(r"<style.*?</style>", " ", txt, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"&nbsp;|&amp;|&#\d+;|&[a-z]+;", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt

def slice_current(text: str) -> str:
    m1 = re.search(re.escape(CUR_MARKER), text, re.I)
    if not m1:
        log("CUR_MARKER not found:", CUR_MARKER)
        return ""
    start = m1.end()
    m2 = re.search(re.escape(NEXT_MARKER), text[start:], re.I)
    end = start + m2.start() if m2 else len(text)
    slice_txt = text[start:end].strip()
    log("---- CURRENT SLICE BEGIN ----")
    log(slice_txt[:800])
    log("---- CURRENT SLICE END ------")
    return slice_txt

def find_zone(slice_txt: str):
    for term in WATCH_TERMS:
        if term in slice_txt.lower():
            return term
    return None

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_state(zone):
    with open(STATE_FILE, "w") as f:
        json.dump({"zone": zone, "ts": int(time.time())}, f)

def send_discord(msg):
    if not DISCORD_URL:
        log("No DISCORD_WEBHOOK_URL set; skipping send.")
        return
    body = {"content": msg}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(DISCORD_URL, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        log("Discord status:", r.status)

def main():
    html = fetch(TARGET_URL)
    text = normalize_text(html)
    cur_slice = slice_current(text)
    if not cur_slice:
        print("ERROR: current slice empty — check markers.")
        return 2

    zone = find_zone(cur_slice)
    if not zone:
        print("No watched zones in Next Terror Zone — exiting.")
        return 0

    print("Matched zone:", zone)

    st = load_state()
    changed = (st.get("zone") != zone)
    if changed or FORCE_SEND or TEST_PING:
        ping = f"<@&{DISCORD_ROLE}>" if DISCORD_ROLE and not TEST_PING else ""
        msg = f"{ping} Next Terror Zone: **{zone}**"
        if TEST_PING:
            msg = f"{ping} TEST PING — sample message."
        send_discord(msg)
        if not TEST_PING:
            save_state(zone)
    else:
        log("Unchanged; not sending.")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
