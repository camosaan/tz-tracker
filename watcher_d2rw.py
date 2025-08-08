import re
from bs4 import BeautifulSoup

# Canonical terror zones (add the full list you care about; longest first helps)
ZONES = sorted([
    "Chaos Sanctuary",
    "Worldstone Keep",
    "The Secret Cow Level",
    "Bloody Foothills",
    "Ancient Tunnels",
    "Tal Rasha's Tombs",
    "Pit",
    "Travincal",
    "Moo Moo Farm",            # if your site uses this label
    "Lower Kurast",
    "Stony Tomb",
    "Arachnid Lair",
    # ... (put the full official TZ names here)
], key=len, reverse=True)

def extract_current_zone(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = re.sub(r'\s+', ' ', text)  # normalize spaces

    # Find the region that describes the CURRENT zone only
    # Adjust the markers to whatever the site actually renders
    start = None
    for marker in ["Current", "Current Zone", "Now", "Active"]:
        m = re.search(rf'\b{re.escape(marker)}\b', text, re.I)
        if m:
            start = m.end()
            break

    end = None
    for marker in ["Next", "Upcoming", "Future"]:
        m = re.search(rf'\b{re.escape(marker)}\b', text[start or 0:], re.I)
        if m:
            end = (start or 0) + m.start()
            break

    slice_text = text[(start or 0):end] if (start is not None) else text

    # Pick the first zone name that appears in the CURRENT slice
    low = slice_text.lower()
    for z in ZONES:
        if z.lower() in low:
            return z

    return None
