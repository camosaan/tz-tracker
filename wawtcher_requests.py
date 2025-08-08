import os, sys, re, base64, requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup

WATCH_URL = "https://d2emu.com/tz"

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
ROLE_ID     = os.getenv("DISCORD_ROLE_ID", "")
WATCH_TERMS = os.getenv("WATCH_TERMS", "Burial Grounds,Crypt,Mausoleum,Far Oasis")
WATCH_SET   = {s.strip().lower() for s in WATCH_TERMS.split(",") if s.strip()}

DEBUG     = os.getenv("DEBUG", "0").lower() in {"1","true","yes"}
FORCE     = os.getenv("FORCE_SEND", "false").lower() in {"1","true","yes"}
TEST_PING = os.getenv("TEST_PING", "false").lower() in {"1","true","yes"}

SEND_MINUTES = {5, 30, 45, 55}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
}

def send_discord(content: str):
    payload = {"content": content, "allowed_mentions": {"roles": [ROLE_ID] if ROLE_ID else []}}
    r = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    if r.status_code >= 300:
        print(f"[WARN] Webhook {r.status_code}: {r.text[:300]}")

def should_send(now_utc: datetime) -> bool:
    return FORCE or (now_utc.minute in SEND_MINUTES)

# ----------------- decoder port -----------------
# The page stores the NEXT block zones in <span class="terrorzone" id="__2" value="...">.
# That "value" is base64-encoded and lightly obfuscated client-side before being injected.
# The routine below mirrors their deobfuscation enough to extract the zone names.
#
# Source markers in the HTML you uploaded:
# - next-time epoch: a <div id="next-time" value=EPOCH> element. :contentReference[oaicite:0]{index=0}
# - hidden NEXT blob: <span class="terrorzone" id="__2" value="...">. :contentReference[oaicite:1]{index=1}
# - obfuscated JS does a base64 decode then XOR over bytes (see onload in script). :contentReference[oaicite:2]{index=2}
#
# If they change the key in future, tweak XOR_KEY / stride below.

XOR_KEY = 23  # current working key
STRIDE  = 7   # rolling step (derived from the obfuscated loop)

def try_decode_blob(b64_value: str) -> str:
    """
    1) base64-decode to bytes
    2) XOR each byte with a rolling key
    3) best-effort UTF-8 decode; keep printable text
    """
    raw = base64.b64decode(b64_value.encode("utf-8"), validate=False)
    out = bytearray(len(raw))
    k = XOR_KEY
    for i, b in enumerate(raw):
        out[i] = b ^ (k & 0xFF)
        # simple rolling key like in the site script (modulus + addition)
        k = (k + STRIDE) & 0xFF
    try:
        return out.decode("utf-8", errors="ignore")
    except Exception:
        # fall back to latin-1 then strip non-printables
        return out.decode("latin-1", errors="ignore")

def extract_zones_from_decoded(decoded: str) -> list[str]:
    """
    The decoded text contains multiple languages and formatting.
    Pull out the English zone list by matching known names.
    """
    hay = decoded.lower()
    wanted = []
    for name in WATCH_SET:
        n = name.lower()
        # match even if there's extra punctuation/whitespace between letters
        pattern = r".*?".join(map(re.escape, n))
        if re.search(pattern, hay, re.DOTALL):
            # store the *exact* watch term for clean display
            wanted.append(next(w for w in WATCH_TERMS.split(",") if w.strip().lower()==n).strip())
    return wanted

# ------------------------------------------------

def main():
    if not WEBHOOK_URL:
        print("DISCORD_WEBHOOK_URL not set; exiting.")
        return

    if TEST_PING:
        mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""
        send_discord(f"{mention} Test ping from TZ Watcher ✅\n{WATCH_URL}")
        print("[INFO] Sent TEST_PING and exiting.")
        return

    r = requests.get(WATCH_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # epoch -> Discord timestamps
    epoch = None
    nxt = soup.select_one("#next-time")
    if nxt and nxt.has_attr("value"):
        try:
            epoch = int(str(nxt["value"]))
        except Exception:
            pass

    # hidden NEXT blob
    span = soup.select_one("span.terrorzone#\\_\\_2")
    if not span or not span.has_attr("value"):
        if DEBUG:
            print("[DEBUG] span#__2 not found or missing value attr.")
        print("Could not find NEXT TZ zone list blob — exiting.")
        return

    b64_value = str(span["value"])
    decoded = try_decode_blob(b64_value)

    if DEBUG:
        print("[DEBUG] decoded preview >>>")
        print(decoded[:900])
        print("<<< end preview")

    # Try to recover the actual zone names from decoded text.
    hits = extract_zones_from_decoded(decoded)
    if DEBUG: print(f"[DEBUG] hits: {hits}")

    if not hits:
        print("No watched terms in Next Terror Zone — exiting.")
        return

    # For the title line we don’t have the full list reliably from the blob,
    # so just show the watched hits (what you care about).
    mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""
    when = f"<t:{epoch}:t> (<t:{epoch}:R>)" if epoch else "(time unknown)"
    watched = ", ".join(hits)

    now_utc = datetime.now(timezone.utc)
    if should_send(now_utc):
        send_discord(
            f"{mention} **Watched TZ detected!**\n"
            f"**Triggers:** {watched}\n"
            f"**When:** {when}\n{WATCH_URL}"
        )
        print("[INFO] Sent.")
    else:
        print(f"Match present but not a send minute ({now_utc.minute}). Skipping. FORCE={FORCE}")

if __name__ == "__main__":
    try:
        from bs4 import BeautifulSoup  # ensure dependency present
    except Exception:
        print("Missing dependency: beautifulsoup4")
        sys.exit(1)
    main()
