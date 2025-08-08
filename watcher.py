# watcher.py
import os, sys, json, time, re, math
from datetime import datetime, timezone
import requests

WATCH_URL = "https://d2emu.com/tz"

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL") or ""
ROLE_ID = os.getenv("DISCORD_ROLE_ID") or ""          # e.g. "1291583820994445355"
WATCH_TERMS = os.getenv("WATCH_TERMS", "Far Oasis,Cows,Chaos Sanctuary")  # comma separated
WATCH_SET = {s.strip().lower() for s in WATCH_TERMS.split(",") if s.strip()}

if not WEBHOOK_URL:
    print("DISCORD_WEBHOOK_URL not set; exiting.")
    sys.exit(0)

try:
    from playwright.sync_api import sync_playwright
except Exception as e:
    print(f"Playwright import failed: {e}")
    sys.exit(1)

def send_discord(message: str):
    try:
        resp = requests.post(WEBHOOK_URL, json={"content": message}, timeout=15)
        if resp.status_code >= 300:
            print(f"[WARN] Webhook returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[ERROR] Webhook error: {e}")

def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        # Load and allow their JS to run
        page.goto(WATCH_URL, wait_until="domcontentloaded")
        # The site fills a <span id="__2"><div>…decoded zone list…</div></span>
        # Wait until that inner <div> has non-empty text
        page.wait_for_function(
            """() => {
                const span = document.querySelector('span#__2');
                if (!span) return false;
                const inner = span.querySelector('div');
                return inner && inner.textContent.trim().length > 0;
            }""",
            timeout=20000
        )

        # Grab zone text (one per line)
        zones_text = page.eval_on_selector("span#\\_\\_2", "el => el.innerText")
        zones = [z.strip() for z in zones_text.splitlines() if z.strip()]
        print(f"[DEBUG] zones: {zones}")

        # Epoch for the next time is in #next-time[value]
        epoch_val = page.eval_on_selector("#next-time", "el => el.getAttribute('value')")
        print(f"[DEBUG] epoch: {epoch_val}")
        try:
            epoch = int(epoch_val)
        except:
            epoch = None

        browser.close()

    if not zones:
        print("Could not locate the Next Terror Zone block — exiting.")
        return

    # Match
    lower = [z.lower() for z in zones]
    hits = [z for z in zones if z.lower() in WATCH_SET]
    print(f"[DEBUG] hits: {hits}")

    if not hits:
        print("No watched terms in Next Terror Zone — exiting.")
        return

    # Build Discord message
    mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""
    if epoch:
        # Discord absolute and relative timestamps
        ts_abs = f"<t:{epoch}:f>"
        ts_rel = f"<t:{epoch}:R>"
        when = f"{ts_abs} ({ts_rel})"
    else:
        when = "(time unknown)"

    title = ", ".join(zones)
    watched = ", ".join(hits)

    msg = (
        f"{mention} **Watched TZ detected!**\n"
        f"**Next Terror Zone:** {title}\n"
        f"**Triggers:** {watched}\n"
        f"**When:** {when}"
    ).strip()

    print("[INFO] Sending webhook…")
    send_discord(msg)
    print("[INFO] Done.")

if __name__ == "__main__":
    main()
