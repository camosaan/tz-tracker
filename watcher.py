import os, re, sys, base64
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

# --------- Env config ----------
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
ROLE_ID = os.environ["DISCORD_ROLE_ID"]        # Discord role id to ping
LOCAL_TZ = os.environ.get("LOCAL_TZ", "Europe/London")
DEBUG = os.environ.get("DEBUG", "0").lower() in {"1", "true", "yes"}
FORCE = os.environ.get("FORCE_SEND", "false").lower() in {"1", "true", "yes"}

DEFAULT_TERMS = ["Burial Grounds", "Crypt", "Mausoleum", "Far Oasis"]
WATCH_TERMS = [t.strip() for t in os.environ.get("WATCH_TERMS", ",".join(DEFAULT_TERMS)).split(",") if t.strip()]
WATCH_TERMS_LC = {t.lower() for t in WATCH_TERMS}

# Send at :05 (initial), then :30, :45, :55 local time
SEND_MINUTES = {5, 30, 45, 55}

URL = "https://d2emu.com/tz"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def fetch_html() -> str:
    r = requests.get(URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def parse_next_epoch_and_blob(html: str) -> tuple[datetime | None, str | None]:
    """
    Extract:
      - next start time from  <div id="next-time" value=EPOCH>
      - base64 zone list from <span class="terrorzone" id="__2" value="...">
    The base64 decodes to a multilingual JSON-ish string that *contains* the zone names.
    We don't need to parse JSON – just substring-match the decoded text.
    """
    soup = BeautifulSoup(html, "html.parser")

    # 1) Epoch time
    epoch_div = soup.find(id="next-time")
    start_local = None
    if epoch_div and epoch_div.has_attr("value"):
        try:
            epoch = int(str(epoch_div["value"]).strip())
            # epoch is seconds since UTC; convert to your LOCAL_TZ
            start_local = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(ZoneInfo(LOCAL_TZ))
        except Exception:
            start_local = None

    # 2) Base64 blob with zone names for the NEXT block (id="__2")
    blob = None
    span_next = soup.find("span", {"class": "terrorzone", "id": "__2"})
    if span_next and span_next.has_attr("value"):
        blob = str(span_next["value"]).strip()

    if DEBUG:
        print(f"[DEBUG] epoch found: {start_local is not None} value={epoch_div['value'] if epoch_div and epoch_div.has_attr('value') else 'None'}")
        print(f"[DEBUG] blob present: {blob is not None}")
        if blob:
            try:
                preview = base64.b64decode(blob.encode("utf-8"), validate=False).decode("utf-8", errors="ignore")
                print("[DEBUG] decoded blob preview >>>")
                print(preview[:700])
                print("<<< end preview")
            except Exception as e:
                print(f"[DEBUG] base64 decode failed: {e}")

    return start_local, blob


def decode_blob(blob: str) -> str:
    try:
        return base64.b64decode(blob.encode("utf-8"), validate=False).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def find_hits(decoded_text: str) -> list[str]:
    low = decoded_text.lower()
    return [t for t in WATCH_TERMS if t.lower() in low]


def should_send_now(now_local: datetime) -> bool:
    return FORCE or (now_local.minute in SEND_MINUTES)


def send_webhook(zones: list[str], start_dt_local: datetime, context_text: str):
    epoch = int(start_dt_local.timestamp())
    abs_tag = f"<t:{epoch}:t>"   # absolute local time for each user
    rel_tag = f"<t:{epoch}:R>"   # relative time, e.g., "in 15 minutes"

    mention = f"<@&{ROLE_ID}>"
    zone_names = ", ".join(zones)

    content = (
        f"{mention} **Terror Zone match: {zone_names}**\n"
        f"Starts at {abs_tag} ({rel_tag})\n"
        f"Source: {URL}"
    )

    # Keep a small snippet for visibility/debug
    snippet = "```\n" + context_text[:1500] + "\n```" if context_text else ""
    r = requests.post(WEBHOOK_URL, json={"content": content + ("\n" + snippet if snippet else "")}, timeout=20)
    r.raise_for_status()


def main():
    tz = ZoneInfo(LOCAL_TZ)
    html = fetch_html()

    start_local, blob = parse_next_epoch_and_blob(html)
    if not blob:
        print("Could not find NEXT TZ zone list blob — exiting.")
        return
    if not start_local:
        print("Could not parse next start time — exiting.")
        return

    decoded = decode_blob(blob)
    if DEBUG:
        print(f"[DEBUG] decoded length: {len(decoded)}")

    hits = find_hits(decoded)
    if DEBUG:
        print(f"[DEBUG] hits: {hits}")

    if not hits:
        print("No watched terms in Next Terror Zone — exiting.")
        return

    now_local = datetime.now(tz)
    if should_send_now(now_local):
        print(f"Sending at {now_local.isoformat()} hits={hits} start={start_local.isoformat()} force={FORCE}")
        send_webhook(hits, start_local, decoded)
    else:
        print(f"Match present but not a send minute ({now_local.minute}). Skipping. force={FORCE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
