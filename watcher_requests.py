import os
import re
import base64
import requests
import zlib
import bz2
import gzip
import io

# ENV VARS from GitHub Secrets
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ROLE_ID = os.getenv("ROLE_ID")
WATCH_TERMS = [t.strip().lower() for t in os.getenv("WATCH_TERMS", "").split(",")]

URL = "https://d2emu.com/tz"

def decode_blob(b64data):
    try:
        raw = base64.b64decode(b64data)
    except Exception as e:
        print(f"[ERROR] Base64 decode failed: {e}")
        return None

    # Try plain UTF-8
    try:
        return raw.decode("utf-8", errors="ignore")
    except:
        pass

    # Try zlib
    try:
        return zlib.decompress(raw).decode("utf-8", errors="ignore")
    except:
        pass

    # Try gzip
    try:
        return gzip.GzipFile(fileobj=io.BytesIO(raw)).read().decode("utf-8", errors="ignore")
    except:
        pass

    # Try bz2
    try:
        return bz2.decompress(raw).decode("utf-8", errors="ignore")
    except:
        pass

    # Try XOR brute (0-255)
    for key in range(256):
        xored = bytes([b ^ key for b in raw])
        if any(term in xored.decode("utf-8", errors="ignore").lower() for term in WATCH_TERMS):
            return xored.decode("utf-8", errors="ignore")

    return None

def send_discord_message(message):
    payload = {
        "content": f"<@&{ROLE_ID}> {message}"
    }
    resp = requests.post(WEBHOOK_URL, json=payload)
    if resp.status_code != 204:
        print(f"[WARN] Webhook {resp.status_code}: {resp.text}")
    else:
        print("[INFO] Discord message sent successfully.")

def main():
    print("[DEBUG] Fetching page…")
    r = requests.get(URL)
    r.raise_for_status()

    html = r.text
    match = re.search(r'id="__2"\s+value="([^"]+)"', html)
    if not match:
        print("[ERROR] Could not find span#__2 value.")
        return

    b64data = match.group(1)
    print(f"[DEBUG] Found encoded blob length: {len(b64data)}")

    decoded = decode_blob(b64data)
    if not decoded:
        print("[ERROR] Failed to decode blob.")
        return

    print("[DEBUG] Decoded blob preview:")
    print(decoded[:300])

    hits = [term for term in WATCH_TERMS if term in decoded.lower()]
    if hits:
        zone_str = ", ".join(hits)
        send_discord_message(f"Matched zones: {zone_str}")
    else:
        print("No watched terms in Next Terror Zone — exiting.")

if __name__ == "__main__":
    main()
