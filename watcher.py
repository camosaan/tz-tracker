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
WATCH_TERMS_LC = {t.lower() for t in WATCH_TERMS}

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

def fetch_dom_block_playwright() -> tuple[str | None, list[str]]:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(20000)
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        # Find the node that *visually* contains "Next Terror Zone:"
        # then walk up to a reasonable container and pull text + link texts.
        result = page.evaluate(
            """
            () => {
              const matchText = (el) => (el && el.innerText || '').toLowerCase().includes('next terror zone');
              const all = Array.from(document.querySelectorAll('body *'));
              const anchor = all.find(el => matchText(el));
              if (!anchor) return null;
              let node = anchor;
              for (let i=0; i<6 && node; i++) {
                const text = (node.innerText || '').trim();
                const links = Array.from(node.querySelectorAll('a'))
                                   .map(a => (a.innerText || '').trim())
                                   .filter(Boolean);
                if (text) return { text, links };
                node = node.parentElement;
              }
              return null;
            }
            """
        )
        browser.close()

        if not result:
            return None, []

        # normalize whitespace
        text = re.sub(r"[ \t]+", " ", result["text"])
        text = re.sub(r"\n+", "\n", text).strip()
        links = [s for s in result.get("links", []) if s]
        return text, links

def parse_next_timestamp(section: str, tz: ZoneInfo) -> datetime | None:
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4}),\s*(\d{1,2}:\d{2}:\d{2})", section)
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

def match_hits(section_text: str, nearby_links: list[str]) -> list[str]:
    candidates = set([s.lower() for s in nearby_links]) | set(section_text.lower().split())
    # Prefer exact link matches first, then fallback to substring in section text
    hits = {t for t in WATCH_TERMS_LC if any(t == link.lower() for link in nearby_links)}
    if not hits:
        # substring fallback on whole block text
        hits = {t for t in WATCH_TERMS_LC if t in section_text.lower()}
    # return in display case
    return [t for t in WATCH_TERMS if t.lower() in hits]

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

    # First try: plain requests (fast)
    html = fetch_html_requests()
    section = _section_from_html(html)
    links = []
    if DEBUG:
        print(f"[DEBUG] requests section found: {bool(section)}")
        if section:
            print("----- SECTION (requests) -----")
            print(section)
            print("----- END SECTION -----")

    # If that didn't include the zone names, render & grab DOM block + links
    if section is None or True:  # always try DOM so we can get links reliably
        if DEBUG:
            print("[DEBUG] Falling back to Playwright DOM extraction…")
        sec2, links2 = fetch_dom_block_playwright()
        if sec2:
            section = sec2
            links = links2
            if DEBUG:
                print(f"[DEBUG] playwright section ok: {bool(section)} links: {links}")
                print("----- SECTION (playwright) -----")
                print(section)
                print("----- END SECTION -----")

    if not section:
        print("Could not extract Next Terror Zone section — exiting.")
        return

    hits = match_hits(section, links)
    if not hits:
        print("No watched terms in Next Terror Zone — exiting.")
        return

    start_dt_local = parse_next_timestamp(section, tz)
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
