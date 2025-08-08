# watcher.py
import os, re, sys
from datetime import datetime, timezone
import requests

WATCH_URL = "https://d2emu.com/tz"

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL") or ""
ROLE_ID = os.getenv("DISCORD_ROLE_ID") or ""
WATCH_TERMS = os.getenv("WATCH_TERMS", "Burial Grounds,Crypt,Mausoleum,Far Oasis")
WATCH_SET = {s.strip().lower() for s in WATCH_TERMS.split(",") if s.strip()}

DEBUG = os.getenv("DEBUG", "0").lower() in {"1", "true", "yes"}
FORCE = os.getenv("FORCE_SEND", "false").lower() in {"1", "true", "yes"}

# :05 (initial) + :30/:45/:55 reminders
SEND_MINUTES = {5, 30, 45, 55}

def send_discord(msg: str):
    try:
        r = requests.post(WEBHOOK_URL, json={"content": msg}, timeout=20)
        if r.status_code >= 300:
            print(f"[WARN] Webhook {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"[ERROR] Webhook error: {e}")

def should_send_now(now_utc: datetime) -> bool:
    # GH runners are UTC; we don't need local tz because Discord timestamps localize for viewers
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
        ctx = browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"))
        page = ctx.new_page()
        page.set_default_timeout(45000)  # be patient; ads/analytics can delay DOM updates

        page.goto(WATCH_URL, wait_until="domcontentloaded")

        # Wait up to 45s for a DIV that has the text and also has UL>LI>A inside
        try:
            page.wait_for_function(
                """
                () => {
                  const containers = Array.from(document.querySelectorAll("div"));
                  for (const c of containers) {
                    const txt = (c.innerText || "").toLowerCase();
                    if (!txt.includes("next terror zone")) continue;
                    const hasLinks = c.querySelector("ul li a");
                    if (hasLinks) return true;
                  }
                  return false;
                }
                """,
                timeout=45000
            )
        except PWTimeout:
            if DEBUG:
                body_preview = page.locator("body").inner_text()[:800]
                print("[DEBUG] Timed out waiting for Next TZ container. Body preview:")
                print(body_preview)
            browser.close()
            print("Could not locate the Next Terror Zone block — exiting.")
            return

        # Extract container text + zone links
        block_text = page.evaluate(
            """
            () => {
              const containers = Array.from(document.querySelectorAll("div"));
              for (const c of containers) {
                const txt = (c.innerText || "");
                if (!txt.toLowerCase().includes("next terror zone")) continue;
                if (!c.querySelector("ul li a")) continue;
                return txt.trim();
              }
              return "";
            }
            """
        ).strip()

        zones = page.evaluate(
            """
            () => {
              const containers = Array.from(document.querySelectorAll("div"));
              for (const c of containers) {
                const txt = (c.innerText || "");
                if (!txt.toLowerCase().includes("next terror zone")) continue;
                const links = c.querySelectorAll("ul li a");
                if (!links.length) continue;
                return Array.from(links).map(a => (a.innerText || "").trim()).filter(Boolean);
              }
              return [];
            }
            """
        )

        # Epoch for next start time is kept in #next-time[value]
        epoch_val = page.evaluate("""() => {
            const n = document.querySelector("#next-time");
            return n ? n.getAttribute("value") : null;
        }""")
        browser.close()

    if DEBUG:
        print("[DEBUG] block snippet >>>")
        print(block_text[:700])
        print("<<< block snippet end")
        print(f"[DEBUG] zones: {zones}")
        print(f"[DEBUG] epoch: {epoch_val}")

    if not zones or not block_text:
        print("Could not locate the Next Terror Zone block — exiting.")
        return

    hits = [z for z in zones if z.lower() in WATCH_SET]
    if DEBUG:
        print(f"[DEBUG] hits: {hits}")
    if not hits:
        print("No watched terms in Next Terror Zone — exiting.")
        return

    # Build Discord message
    mention = f"<@&{ROLE_ID}>" if ROLE_ID else ""
    when = "(time unknown)"
    try:
        epoch = int(epoch_val) if epoch_val else None
    except:
        epoch = None
    if epoch:
        when = f"<t:{epoch}:t> (<t:{epoch}:R>)"  # absolute + relative, auto-localized

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
        ).strip()
        print("[INFO] Sending webhook…")
        send_discord(msg)
        print("[INFO] Done.")
    else:
        print(f"Match present but not a send minute ({now_utc.minute}). Skipping. force={FORCE}")

if __name__ == "__main__":
    main()
