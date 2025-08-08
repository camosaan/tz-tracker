import random, time, urllib.error

UA_POOL = [
    # Chrome (Win, Mac, Linux); rotate to look normal
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

def _headers():
    return {
        "User-Agent": random.choice(UA_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
        "Referer": "https://d2runewizard.com/",
    }

ALT_URLS = [
    "https://d2runewizard.com/terror-zone-tracker",
    # add a backup if you want:
    # "https://d2emu.com/tz",  # example mirror
]

def fetch(url: str) -> str:
    last_err = None
    for attempt in range(1, 6):  # up to 5 tries across alt URLs
        for target in ([url] + [u for u in ALT_URLS if u != url]):
            try:
                if DEBUG:
                    print(f"[DEBUG] Fetching (try {attempt}): {target}")
                req = urllib.request.Request(target, headers=_headers())
                with urllib.request.urlopen(req, timeout=25) as r:
                    html = r.read().decode("utf-8", "ignore")
                if DEBUG:
                    print("[DEBUG] Got HTML length:", len(html))
                return html
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code == 403 or e.code == 429:
                    # backoff a bit and rotate UA
                    time.sleep(1.2 * attempt)
                    continue
                else:
                    raise
            except Exception as e:
                last_err = e
                time.sleep(0.8 * attempt)
                continue
    raise last_err
