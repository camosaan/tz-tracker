import os, re, sys
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
ROLE_ID = os.environ["DISCORD_ROLE_ID"]
LOCAL_TZ = os.environ.get("LOCAL_TZ", "Europe/London")
DEBUG = os.environ.get("DEBUG", "0") in {"1", "true", "True"}

_default_terms = ["Burial Grounds", "Crypt", "Mausoleum", "Far Oasis"]
WATCH_TERMS = [t.strip() for t in os.environ.get("WATCH_TERMS", ",".join(_default_terms)).split(",") if t.strip()]

SEND_MINUTES = {5, 30, 45, 55}
URL = "https://d2emu.com/tz"

def _extract_next_section_from_text(full_text: str) -> str | None:
    m = re.search(r"(Next\s*Terror\s*Zone:.*?)(Current\s*Terror\s*Zone:|$)", full_text, re.I | re.S)
    if not m:
        return None
    section = m.group(1)
    section = re.sub(r"[ \t]+", " ", section)
    section = re.sub(r"\n+", "\n", section).strip()
    return section

def _section_from_html(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    return _extract_next_section_from_text(text)

def fetch_html_requests() -> str:
    r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.raise_for_status()
    return r.text

def fetch_html_playwright() -> str:
    # Lazy import so Actions without Playwright install won’t crash unless needed
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(20000)
        page.goto(URL, wait_until="domcontentloaded")
        # Give any client-side rendering a brief moment
        page.wait_for_timeout(1500)
        html = page.content()
        browser.close()
        return html

def parse_next_timestamp(section: str, tz: ZoneInfo) -> datetime | None:
    m = re.search(r"(\d{2}/\d{2}/\d{4}),\s*(\d{2}:\d{2}:\d{2})", section)
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

def find_hits(section: str) -> list[str]:
    low = section.lower()
    return sorted([t for t in WATCH_TERMS if t.lower() in low], key=lambda s: s.lower())

def should_send_now(now_local: datetime, force: bool) -> bool:
    return force or (now_local.minute in SEND_MINUTES)

def send_webhook(zones: list[str], start_dt_local: datetime, section: str):
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
    snippet = "```\n" + section[:1700] + "\n```"
    r = requests.post(WEBHOOK_URL, json={"content": content + "\n" + snippet}, timeout=20)
    r.raise_for_status()

def main():
    force = os.environ.get("FORCE_SEND", "").lower() in {"1", "true", "yes"}
    tz = ZoneInfo(LOCAL_TZ)

    def try_once(fetcher_name: str, html: str):
        section = _section_from_html(html)
        if DEBUG:
            print(f"[DEBUG] Using {fetcher_name}. Found section: {section is not None}")
            if section:
                print("----- SECTION START -----")
                print(section)
                print("------ SECTION END ------")
        if not section:
            return None, None, None
        hits = find_hits(section)
        start_dt_local = parse_next_timestamp(section, tz)
        return section, hits, start_dt_local

    # 1) Try plain requests
    html = fetch_html_requests()
    section, hits, start_dt_local = try_once("requests", html)

    # 2) If we failed to find a section or hits, try Playwright render
    if not section or (section and not hits):
        if DEBUG:
            print("[DEBUG] Falling back to Playwright…")
        try:
            html2 = fetch_html_playwright()
            section2, hits2, start_dt_local2 = try_once("playwright", html2)
            # Prefer the successful Playwright parse
            if section2:
                section, hits, start_dt_local = section2, hits2, start_dt_local2
        except Exception as e:
            print(f"[DEBUG] Playwright fetch failed: {e}")

    # Final decision
    if not section:
        print("Could not extract Next Terror Zone section — exiting.")
        return
    if not hits:
        print("No watched terms in Next Terror Zone — exiting.")
        return
    if not start_dt_local:
        print("Could not parse timestamp; skipping send to avoid wrong times.")
        return

    now_local = datetime.now(tz)
    if should_send_now(now_local, force):
        print(f"Sending at {now_local.isoformat()} hits={hits} start={start_dt_local.isoformat()} force={force}")
        send_webhook(hits, start_dt_local, section)
    else:
        print(f"Match present but not a send minute ({now_local.minute}). Skipping. force={force}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
