# watcher.py
import os, sys, requests
from datetime import datetime, timezone

WATCH_URL = "https://d2emu.com/tz"
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL") or ""
ROLE_ID = os.getenv("DISCORD_ROLE_ID") or ""
WATCH_TERMS = os.getenv("WATCH_TERMS", "Burial Grounds,Crypt,Mausoleum,Far Oasis")
WATCH_SET = {s.strip().lower() for s in WATCH_TERMS.split(",") if s.strip()}

DEBUG = os.getenv("DEBUG", "0").lower() in {"1", "true", "yes"}
FORCE = os.getenv("FORCE_SEND", "false").lower() in {"1", "true", "yes"}
SEND_MINUTES = {5, 30, 45, 55}

def send_discord(msg: str):
    try:
        r = requests.post(WEBHOOK_URL, json={"content": msg}, timeout=20)
        if r.status_code >= 300:
            print(f"[WARN] Webhook {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"[ERROR] Webhook error: {e}")

def should_send_now(now_utc: datetime) -> bool:
    return FORCE or (now_utc.minute in SEND_MINUTES)

def main():
    if not WEBHOOK_URL:
        print("DISCORD_WEBHOOK_URL not set; exiting.")
        return

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except Exception as e:
        print(f"Playwright import failed: {e}")
        sys.exit(1)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.set_default_timeout(45000)

        page.goto(WATCH_URL, wait_until="domcontentloaded")

        try:
            # Wait for the timestamp element
            page.wait_for_selector("#next-time", timeout=20000)
            # Wait for the span#__2 zone list to be filled
            page.wait_for_function(
                """() => {
                    const span = document.querySelector('span#__2');
                    return span && span.innerText.trim().length > 0;
                }""",
                timeout=25000
            )
        except PWTimeout:
            if DEBUG:
                print("[DEBUG] Timed out waiting for zones.")
                print(page.locator("body").inner_text()[:800])
            browser.close()
            print("Could not locate the Next Terror Zone block — exiting.")
            return

        # Extract zones
        zones_text = page.inner_text("span#__2").strip()
        zones = [z.strip() for z in zones_text.splitlines() if z.strip()]
        # Extract epoch time
        epoch_val = page.get_attribute("#next-time", "value")
        browser.close()

    if DEBUG:
        print(f"[DEBUG] zones: {zones}")
        print(f"[DEBUG] epoch: {epoch_val}")

    if not zones:
        print("No zones detected — exiting.")
        return

    hits = [z for z in zones if z.lower() in WATCH_SET]
    if DEBUG:
        print(f"[DEBUG] hits: {hits}")
    if not hits:
        print("No watched terms in Next Terror Zone — exiting.")
        return

    mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""
    when = "(time unknown)"
    try:
        epoch = int(epoch_val) if epoch_val else None
    except:
        epoch = None
    if epoch:
        when = f"<t:{epoch}:t> (<t:{epoch}:R>)"

    title = ", ".join(zones)
    watched = ", ".join(hits)

    now_utc = datetime.now(timezone.utc)
    if should_send_now(now_utc):
        msg = (
            f"{mention} **Watched TZ detected!**\n"
            f"**Next Terror Zone:** {title}\n"
            f"**Triggers:** {watched}\n"
            f"**When:** {when}\n"
            f"{WATCH_URL}"
        )
        print("[INFO] Sending webhook…")
        send_discord(msg)
        print("[INFO] Done.")
    else:
        print(f"Match present but not a send minute ({now_utc.minute}). Skipping. force={FORCE}")

if __name__ == "__main__":
    main()
