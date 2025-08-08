import os, sys, requests
from datetime import datetime, timezone

WATCH_URL = "https://d2emu.com/tz"

# --- env ---
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
ROLE_ID     = os.getenv("DISCORD_ROLE_ID", "")
WATCH_TERMS = os.getenv("WATCH_TERMS", "Burial Grounds,Crypt,Mausoleum,Far Oasis")
WATCH_SET   = {s.strip().lower() for s in WATCH_TERMS.split(",") if s.strip()}

DEBUG     = os.getenv("DEBUG", "0").lower() in {"1","true","yes"}
FORCE     = os.getenv("FORCE_SEND", "false").lower() in {"1","true","yes"}
TEST_PING = os.getenv("TEST_PING", "false").lower() in {"1","true","yes"}

SEND_MINUTES = {5, 30, 45, 55}  # UTC minutes. Discord timestamps localize.

def send_discord(content: str):
    payload = {"content": content, "allowed_mentions": {"roles": [ROLE_ID] if ROLE_ID else []}}
    r = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    if r.status_code >= 300:
        print(f"[WARN] Webhook {r.status_code}: {r.text[:300]}")

def should_send(now_utc: datetime) -> bool:
    return FORCE or (now_utc.minute in SEND_MINUTES)

def main():
    if not WEBHOOK_URL:
        print("DISCORD_WEBHOOK_URL not set; exiting.")
        return

    # quick wiring test
    if TEST_PING:
        mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""
        send_discord(f"{mention} Test ping from TZ Watcher ✅\n{WATCH_URL}")
        print("[INFO] Sent TEST_PING and exiting.")
        return

    # ---- real scrape with stealth ----
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        from playwright_stealth import stealth_sync
    except Exception as e:
        print(f"[ERROR] Playwright/stealth import failed: {e}")
        sys.exit(1)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
            viewport={"width": 1366, "height": 768},
            locale="en-GB",
            timezone_id="Etc/UTC",
        )
        page = ctx.new_page()
        stealth_sync(page)  # soften webdriver fingerprints

        # extra anti-bot hardening
        page.add_init_script("""() => {
          Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
          // Simulate plugins & languages
          Object.defineProperty(navigator, 'languages', {get: () => ['en-GB','en']});
          Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
        }""")

        page.set_default_timeout(60000)
        page.goto(WATCH_URL, wait_until="domcontentloaded")

        try:
            # epoch present?
            page.wait_for_selector("#next-time", timeout=30000)
            # site injects zone list into span#__2 (as innerText)
            page.wait_for_function(
                "() => {const s=document.querySelector('span#__2'); return s && s.innerText.trim().length>0;}",
                timeout=45000
            )
        except PWTimeout:
            if DEBUG:
                print("[DEBUG] Timed out; body preview:\n", page.locator("body").inner_text()[:900])
            browser.close()
            print("Could not locate the Next Terror Zone block — exiting.")
            return

        zones = [z.strip() for z in page.inner_text("span#__2").splitlines() if z.strip()]
        epoch_val = page.get_attribute("#next-time", "value")
        browser.close()

    if DEBUG:
        print(f"[DEBUG] zones: {zones}")
        print(f"[DEBUG] epoch: {epoch_val}")

    if not zones:
        print("No zones detected — exiting.")
        return

    hits = [z for z in zones if z.lower() in WATCH_SET]
    if DEBUG: print(f"[DEBUG] hits: {hits}")
    if not hits:
        print("No watched terms in Next Terror Zone — exiting.")
        return

    mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""
    when = "(time unknown)"
    try:
        epoch = int(epoch_val) if epoch_val else None
        if epoch: when = f"<t:{epoch}:t> (<t:{epoch}:R>)"
    except: pass

    title = ", ".join(zones)
    watched = ", ".join(hits)
    now_utc = datetime.now(timezone.utc)

    if should_send(now_utc):
        send_discord(
            f"{mention} **Watched TZ detected!**\n"
            f"**Next Terror Zone:** {title}\n"
            f"**Triggers:** {watched}\n"
            f"**When:** {when}\n{WATCH_URL}"
        )
        print("[INFO] Sent.")
    else:
        print(f"Match present but not a send minute ({now_utc.minute}). Skipping. FORCE={FORCE}")

if __name__ == "__main__":
    main()
