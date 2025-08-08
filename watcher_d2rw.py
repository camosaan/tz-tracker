#!/usr/bin/env python3
import os, sys, re, json, time
from urllib import request, error
from html import unescape

TARGET_URL = os.environ.get("TARGET_URL", "https://d2runewizard.com/terror-zone-tracker")

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
DISCORD_ROLE_ID     = os.environ.get("DISCORD_ROLE_ID", "").strip()
WATCH_TERMS         = [t.strip() for t in os.environ.get("WATCH_TERMS", "").split(",") if t.strip()]
DEBUG               = os.environ.get("DEBUG", "false").lower() == "true"
FORCE_SEND          = os.environ.get("FORCE_SEND", "false").lower() == "true"
TEST_PING           = os.environ.get("TEST_PING", "false").lower() == "true"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://d2runewizard.com/",
    "Connection": "keep-alive",
}

def log(msg):
    print(msg, flush=True)

def fetch(url, retries=3, timeout=20):
    for attempt in range(1, retries+1):
        try:
            req = request.Request(url, headers=HEADERS)
            with request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="ignore")
        except error.HTTPError as e:
            if e.code in (403, 429) and attempt < retries:
                if DEBUG: log(f"[DEBUG] {e.code} from server. Sleeping then retrying ({attempt}/{retries})…")
                time.sleep(2 * attempt)
                continue
            raise
        except Exception:
            if attempt == retries:
                raise
            if DEBUG: log(f"[DEBUG] fetch error on attempt {attempt}, retrying…")
            time.sleep(1.5 * attempt)

def _textify(html):
    # Rip out tags, collapse whitespace to make regex easier
    txt = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    txt = re.sub(r"<style[\s\S]*?</style>", " ", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = unescape(txt)
    txt = re.sub(r"[ \t\r\f\v]+", " ", txt)
    txt = re.sub(r"\n+", " ", txt)
    return txt.strip()

def parse_current_next(html):
    """
    We try multiple patterns because Next.js markup can vary.
    We first try a quick pass on the raw HTML (sometimes labels live in data-json),
    then we fall back to a textified sweep.
    """
    # 1) Try to pull JSON from __NEXT_DATA__ (often present)
    m = re.search(r'__NEXT_DATA__"[^>]*>\s*({[\s\S]*?})\s*<', html)
    if m:
        try:
            data = json.loads(m.group(1))
            # Best-effort walk for anything that looks like current/next zones
            jtext = json.dumps(data, separators=(",", ":"))
            cur = None
            nxt = None
            # Look for obvious fields
            for key in ("currentTerrorZone", "currentZone", "current", "tzCurrent"):
                mm = re.search(rf'"{key}"\s*:\s*"([^"]+)"', jtext, flags=re.I)
                if mm:
                    cur = mm.group(1)
                    break
            for key in ("nextTerrorZone", "nextZone", "nextZones", "tzNext"):
                mm = re.search(rf'"{key}"\s*:\s*"([^"]+)"', jtext, flags=re.I)
                if mm:
                    nxt = mm.group(1)
                    break
            if cur or nxt:
                return (cur or "").strip(), (nxt or "").strip()
        except Exception:
            pass

    # 2) Fallback: text sweep
    txt = _textify(html)

    # Current TZ
    cur_patterns = [
        r"Current\s*Terror\s*Zone[^:]*:\s*([A-Za-z0-9 ,'&\-]+)",
        r"Current\s*TZ\s*:\s*([A-Za-z0-9 ,'&\-]+)",
        r"Current\s*Zone\s*:\s*([A-Za-z0-9 ,'&\-]+)",
        r"Current\s+([A-Za-z0-9 ,'&\-]+)\s+Next",  # between Current ... Next
    ]
    current = ""
    for p in cur_patterns:
        mm = re.search(p, txt, flags=re.I)
        if mm:
            current = mm.group(1).strip(" -")
            break

    # Next TZ (can be comma-separated list)
    next_patterns = [
        r"Next\s*Terror\s*Zone[^:]*:\s*([A-Za-z0-9 ,'/&\-]+)",
        r"Next\s*TZ\s*:\s*([A-Za-z0-9 ,'/&\-]+)",
        r"Next\s*Zone[s]?\s*:\s*([A-Za-z0-9 ,'/&\-]+)",
    ]
    next_raw = ""
    for p in next_patterns:
        mm = re.search(p, txt, flags=re.I)
        if mm:
            next_raw = mm.group(1).strip(" -")
            break

    # Normalize: sometimes it's like "Bloody Foothills, Frigid Highlands, Abaddon"
    next_list = [s.strip() for s in re.split(r",|\s/\s", next_raw) if s.strip()]
    next_str = ", ".join(next_list) if next_list else next_raw

    return current, next_str

def should_notify(current_zone):
    if FORCE_SEND:
        return True
    if not WATCH_TERMS:
        return False
    cz = current_zone.lower()
    return any(term.lower() in cz for term in WATCH_TERMS)

def send_discord(msg):
    if not DISCORD_WEBHOOK_URL:
        if DEBUG: log("[DEBUG] No DISCORD_WEBHOOK_URL set; skipping send.")
        return
    body = {"content": msg}
    data = json.dumps(body).encode("utf-8")
    req = request.Request(DISCORD_WEBHOOK_URL, data=data, headers={
        "User-Agent": UA,
        "Content-Type": "application/json",
    })
    with request.urlopen(req, timeout=15) as r:
        r.read()  # drain

def main():
    if DEBUG:
        log(f"[DEBUG] Fetching: {TARGET_URL}")

    try:
        html = fetch(TARGET_URL)
    except Exception as e:
        log(f"[ERROR] fetch failed: {e}")
        sys.exit(1)

    current, next_str = parse_current_next(html)

    if DEBUG:
        log(f"[DEBUG] Current TZ: {current or '(not found)'}")
        log(f"[DEBUG] Next TZ: {next_str or '(not found)'}")

    # Compose message (and mention) if we’re notifying
    mention = ""
    if DISCORD_ROLE_ID and (TEST_PING or should_notify(current)):
        mention = f"<@&{DISCORD_ROLE_ID}> "

    if FORCE_SEND or should_notify(current):
        content = f"{mention}Current Terror Zone: **{current or 'Unknown'}**"
        if next_str:
            content += f"\nNext: {next_str}"
        try:
            send_discord(content)
            log("[INFO] Discord notification sent.")
        except Exception as e:
            log(f"[ERROR] Discord send failed: {e}")
            sys.exit(1)
    else:
        if DEBUG:
            log("[DEBUG] No notification criteria met. (Either no WATCH_TERMS or no match and FORCE_SEND=false)")

if __name__ == "__main__":
    main()
