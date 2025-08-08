# watcher_requests.py
import os, sys, re, base64, gzip, zlib, bz2, io, requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from urllib.parse import urlparse

WATCH_URL = "https://d2emu.com/tz"

# ---- ENV (matches your workflow) ----
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
ROLE_ID     = os.getenv("DISCORD_ROLE_ID", "").strip()
WATCH_TERMS = os.getenv("WATCH_TERMS", "Burial Grounds,Crypt,Mausoleum,Far Oasis")
WATCH_SET   = {s.strip().lower() for s in WATCH_TERMS.split(",") if s.strip()}

DEBUG       = os.getenv("DEBUG", "0").lower() in {"1","true","yes"}
FORCE       = os.getenv("FORCE_SEND", "false").lower() in {"1","true","yes"}
TEST_PING   = os.getenv("TEST_PING", "false").lower() in {"1","true","yes"}

SEND_MINUTES = {5, 30, 45, 55}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
}

def validate_webhook(url: str) -> str | None:
    if not url:
        return "Missing DISCORD_WEBHOOK_URL."
    try:
        u = urlparse(url)
    except Exception:
        return "Malformed webhook URL."
    if u.scheme not in ("http", "https"):
        return "Webhook must be http/https."
    parts = [p for p in u.path.split("/") if p]
    try:
        api_idx = parts.index("api")
        if parts[api_idx+1] != "webhooks":
            return "Webhook path must contain /api/webhooks/…"
        _id = parts[api_idx+2]
        _token = parts[api_idx+3]
        if not _id.isdigit() or len(_token) < 20:
            return "Webhook missing numeric id or long token."
    except Exception:
        return "Webhook path incomplete (need /api/webhooks/<id>/<token>)."
    return None

def send_discord(content: str):
    payload = {
        "content": content,
        "allowed_mentions": {"roles": [ROLE_ID] if ROLE_ID else []},
    }
    r = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    if r.status_code >= 300:
        print(f"[WARN] Webhook {r.status_code}: {r.text[:300]}")

def should_send(now_utc: datetime) -> bool:
    return FORCE or (now_utc.minute in SEND_MINUTES)

# -------- decoding helpers --------
def b64(s: str) -> bytes | None:
    try:
        return base64.b64decode(s.encode("utf-8"), validate=False)
    except Exception:
        return None

def try_utf8(b: bytes) -> str | None:
    try:
        return b.decode("utf-8")
    except Exception:
        return b.decode("utf-8", errors="ignore") if b else None

def gen_candidates(raw: bytes) -> list[str]:
    cand: list[str] = []

    t = try_utf8(raw)
    if t: cand.append(t)

    # zlib/deflate (both wbits)
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            dec = zlib.decompress(raw, wbits=wbits)
            txt = try_utf8(dec)
            if txt: cand.append(txt)
        except Exception:
            pass

    # gzip
    try:
        dec = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        txt = try_utf8(dec)
        if txt: cand.append(txt)
    except Exception:
        pass

    # bz2
    try:
        dec = bz2.decompress(raw)
        txt = try_utf8(dec)
        if txt: cand.append(txt)
    except Exception:
        pass

    # single-byte XOR sweep
    for k in range(256):
        x = bytes(b ^ k for b in raw)
        txt = try_utf8(x)
        if txt:
            cand.append(txt)

    # de-dup
    seen, out = set(), []
    for s in cand:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out

def find_hits(text: str) -> list[str]:
    low = text.lower()
    return [w.strip() for w in WATCH_TERMS.split(",") if w.strip() and w.strip().lower() in low]

# -------------- main --------------
def main():
    err = validate_webhook(WEBHOOK_URL)
    if err:
        print(f"[CONFIG ERROR] {err}")
        sys.exit(1)

    if TEST_PING:
        mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""
        send_discord(f"{mention} Test ping from TZ Watcher ✅\n{WATCH_URL}")
        print("[INFO] Sent TEST_PING and exiting.")
        return

    print("[DEBUG] Fetching page…")
    r = requests.get(WATCH_URL, headers=HEADERS, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # epoch for Discord timestamps
    epoch = None
    nxt = soup.select_one("#next-time")
    if nxt and nxt.has_attr("value"):
        try:
            epoch = int(str(nxt["value"]))
        except Exception:
            epoch = None
    if DEBUG:
        print(f"[DEBUG] epoch attr present: {bool(epoch)} value={epoch}")

    span = soup.select_one("span.terrorzone#\\_\\_2")
    if not span or not span.has_attr("value"):
        print("Could not find NEXT TZ zone blob — exiting.")
        return

    b64val = str(span["value"])
    print(f"[DEBUG] Found encoded blob length: {len(b64val)}")
    raw = b64(b64val)
    if raw is None:
        print("Base64 decode failed — exiting.")
        return

    candidates = gen_candidates(raw)
    if DEBUG:
        print(f"[DEBUG] decode candidates: {len(candidates)}")
        for i, s in enumerate(candidates[:5]):
            print(f"[DEBUG] cand[{i}] >>> {s[:180].replace(chr(10),' ')} ...")

    hits: list[str] = []
    chosen: str | None = None
    for s in candidates:
        hits = find_hits(s)
        if hits:
            chosen = s
            break

    print(f"[DEBUG] hits: {hits}")
    if not hits:
        print("No watched terms in Next Terror Zone — exiting.")
        return

    mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""
    when = f"<t:{epoch}:t> (<t:{epoch}:R>)" if epoch else "(time unknown)"
    watched = ", ".join(hits)
    snippet = ""
    if DEBUG and chosen:
        snippet = "\n```\n" + chosen[:700] + "\n```"

    now_utc = datetime.now(timezone.utc)
    if should_send(now_utc):
        send_discord(
            f"{mention} **Watched TZ detected!**\n"
            f"**Triggers:** {watched}\n"
            f"**When:** {when}\n{WATCH_URL}{snippet}"
        )
        print("[INFO] Sent.")
    else:
        print(f"Match present but not a send minute ({now_utc.minute}). Skipping. FORCE={FORCE}")

if __name__ == "__main__":
    try:
        from bs4 import BeautifulSoup  # dependency check
    except Exception:
        print("Missing dependency: beautifulsoup4")
        sys.exit(1)
    main()
