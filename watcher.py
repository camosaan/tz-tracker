import os, re, sys
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
ROLE_ID = os.environ["DISCORD_ROLE_ID"]

LOCAL_TZ = os.environ.get("LOCAL_TZ", "Europe/London")
DEBUG = os.environ.get("DEBUG", "0").lower() in {"1", "true", "yes"}
FORCE = os.environ.get("FORCE_SEND", "false").lower() in {"1", "true", "yes"}

DEFAULT_TERMS = ["Burial Grounds", "Crypt", "Mausoleum", "Far Oasis"]
WATCH_TERMS = [t.strip() for t in os.environ.get("WATCH_TERMS", ",".join(DEFAULT_TERMS)).split(",") if t.strip()]
WATCH_TERMS_LC = {t.lower() for t in WATCH_TERMS}

SEND_MINUTES = {5, 30, 45, 55}
URL = "https://d2emu.com/tz"

# ---------- robust Playwright extraction (anchor + ancestor with links) ----------
def fetch_next_tz_playwright() -> tuple[str | None, list[str]]:
    """
    Find element containing 'Next Terror Zone', walk up ancestors until we find
    a container that ALSO has 'ul li a' zone links. Return (container_text, zones[]).
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(25000)
        page.goto(URL, wait_until="load")
        page.wait_for_timeout(1500)

        try:
            anchor = page.locator("text=Next Terror Zone").first
            anchor.wait_for(state="visible", timeout=5000)
        except PWTimeout:
            if DEBUG: print("[DEBUG] Could not find visible 'Next Terror Zone' anchor.")
            browser.close()
            return None, []

        result = page.evaluate(
            """
            (anchor) => {
              // climb up to 12 ancestors; pick the first that has at least one UL->LI->A
              let node = anchor;
              for (let i=0; i<12 && node; i++) {
                const links = Array.from(node.querySelectorAll("ul li a"))
                                    .map(a => (a.innerText || "").trim())
                                    .filter(Boolean);
                const text = (node.innerText || "").trim();
                if (links.length && text.toLowerCase().includes("next terror zone")) {
                  return {text, links};
                }
                node = node.parentElement;
              }
              // fallback: search sibling containers
              node = anchor.parentElement;
              for (let i=0; i<12 && node; i++) {
                const sibs = Array.from(node.children);
                for (const s of sibs) {
                  const links = Array.from(s.querySelectorAll("ul li a"))
                                      .map(a => (a.innerText || "").trim())
                                      .filter(Boolean);
                  const text = (s.innerText || "").trim();
                  if (links.length && text.toLowerCase().includes("next terror zone")) {
                    return {text, links};
                  }
                }
                node = node.parentElement;
              }
              return null;
            }
            """,
            anchor
        )

        browser.close()

        if not result:
            return None, []

        # normalize whitespace
        text = re.sub(r"[ \t]+", " ", result["text"])
        text = re.sub(r"\n+", "\n", text).strip()
        zones = [s for s in result.get("links", []) if s]
        return text, zones

# ----------------------- helpers -----------------------
def parse_next_timestamp(block_text: str, tz: ZoneInfo) -> datetime | None:
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2}:\d{2})", block_text or "")
    if not m:
        return None
    d, t = m.group(1), m.group(2)
    for fmt in ("%d/%m/%Y, %H:%M:%S", "%m/%d/%Y, %H:%M:%S"):
        try:
            dt_naive = datetime.strptime(f"{d}, {t}", fmt)
            return dt_naive.replace(tzinfo=tz)
        except ValueError:
            continue
    return None

def should_send_now(now_local: datetime) -> bool:
    return FORCE or (now_local.minute in SEND_MINUTES)

def send_webhook(zones: list[str], start_dt_local: datetime, context_text: str):
    epoch = int(start_dt_local.timestamp())
    abs_tag = f"<t:{epoch}:t>"
    rel_tag = f"<t:{epoch}:R>"
    mention = f"<@&{ROLE_ID}>"
    zone_names = ", ".join(zones)

    content = (
        f"{mention} **Terror Zone match: {zone_names}**\n"
        f"Starts at {abs_tag} ({rel_tag})\n"
        f"Source: {URL}"
    )
    snippet = "```\n" + (context_text[:1700] if context_text else "") + "\n```"
    r = requests.post(WEBHOOK_URL, json={"content": content + "\n" + snippet}, timeout=20)
    r.raise_for_status()

# ----------------------- main -----------------------
def main():
    tz = ZoneInfo(LOCAL_TZ)

    block_text, zones = fetch_next_tz_playwright()
    if DEBUG:
        print(f"[DEBUG] block_text present: {bool(block_text)}")
        if block_text:
            print("---- BLOCK (Next TZ) ----")
            print(block_text)
            print("-------- END ---------")
        print(f"[DEBUG] zones: {zones}")

    if not block_text:
        print("Could not locate the Next Terror Zone block — exiting.")
        return

    hits = [z for z in zones if z.lower() in WATCH_TERMS_LC]
    if DEBUG: print(f"[DEBUG] hits after filter: {hits}")
    if not hits:
        print("No watched terms in Next Terror Zone — exiting.")
        return

    start_dt_local = parse_next_timestamp(block_text, tz)
    if not start_dt_local:
        print("Could not parse timestamp; skipping send to avoid wrong times.")
        return

    now_local = datetime.now(tz)
    if should_send_now(now_local):
        print(f"Sending at {now_local.isoformat()} hits={hits} start={start_dt_local.isoformat()} force={FORCE}")
        send_webhook(hits, start_dt_local, block_text)
    else:
        print(f"Match present but not a send minute ({now_local.minute}). Skipping. force={FORCE}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
