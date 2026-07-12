"""
Rental listings -> Telegram notifier (Amsterdam)
Tries Pararius first; falls back to huurwoningen.nl (same company, same
listings, same page structure). Sends only NEW listings. If scraping fails,
it reports the error INTO your Telegram channel so you always know the status.
"""

import json
import os
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ----------------- SETTINGS (edit these) -----------------
SOURCES = [
    # Tried in order; all working sources are used each run.
    # Build your own filter URLs on the sites and paste them here.
    "https://www.pararius.com/apartments/amsterdam/0-1600",
    "https://www.huurwoningen.nl/in/amsterdam/?price=0-1600",
]
MAX_SENDS_PER_RUN = 10
SEEN_FILE = Path("seen.json")
MAX_SEEN_STORED = 3000
# ----------------------------------------------------------

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,nl;q=0.8",
    "Referer": "https://www.google.com/",
}


def tg_text(text: str) -> None:
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True},
        timeout=30,
    )


def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set) -> None:
    SEEN_FILE.write_text(json.dumps(list(seen)[-MAX_SEEN_STORED:], indent=0))


def base_of(url: str) -> str:
    # "https://www.pararius.com/..." -> "https://www.pararius.com"
    return "/".join(url.split("/")[:3])


def fetch_listings() -> tuple[list[dict], list[str]]:
    """Returns (listings, errors). Both sites share the same HTML structure."""
    listings, errors = [], []
    for search_url in SOURCES:
        base = base_of(search_url)
        try:
            resp = requests.get(search_url, headers=HEADERS, timeout=30)
        except Exception as e:
            errors.append(f"{base}: {type(e).__name__}")
            continue
        if resp.status_code != 200:
            errors.append(f"{base}: HTTP {resp.status_code}")
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("section.listing-search-item, li.search-list__item--listing")
        found = 0
        for item in cards:
            link = item.select_one(
                "a.listing-search-item__link--title, h2 a, a.listing-search-item__link"
            )
            if not link or not link.get("href"):
                continue
            href = link["href"]
            url = href if href.startswith("http") else base + href
            price_el = item.select_one(".listing-search-item__price")
            addr_el = item.select_one(
                ".listing-search-item__sub-title, .listing-search-item__sub-title\\'"
            )
            img_el = item.select_one("img")
            img = img_el.get("src") or img_el.get("data-src") if img_el else None
            listings.append(
                {
                    "id": url,
                    "url": url,
                    "title": link.get_text(strip=True),
                    "price": price_el.get_text(strip=True) if price_el else "N/A",
                    "address": addr_el.get_text(strip=True) if addr_el else "",
                    "image": img,
                }
            )
            found += 1
        if found == 0:
            errors.append(f"{base}: page loaded but 0 listings parsed")
    return listings, errors


def send_listing(listing: dict) -> None:
    caption = (
        f"🏠 {listing['title']}\n"
        f"💶 {listing['price']}\n"
        f"📍 {listing['address']}\n"
        f"🔗 {listing['url']}"
    )
    if listing["image"] and str(listing["image"]).startswith("http"):
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id": CHAT_ID, "photo": listing["image"], "caption": caption},
            timeout=30,
        )
        if r.ok:
            return
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": caption},
        timeout=30,
    )


def main() -> int:
    # Manual "Run workflow" click -> send a startup ping BEFORE scraping.
    # This proves GitHub + secrets + Telegram all work, independent of the
    # websites. Scheduled runs stay silent (no spam every 5 minutes).
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        tg_text("🤖 Bot started (manual run). GitHub + Telegram connection OK.")

    first_run = not SEEN_FILE.exists()
    seen = load_seen()
    listings, errors = fetch_listings()
    print(f"Parsed {len(listings)} listings. Errors: {errors or 'none'}")

    if not listings:
        # Tell the channel exactly what went wrong (max once — only on first
        # run or if we've never succeeded, to avoid spamming every 5 min).
        if first_run:
            tg_text("⚠️ Bot could not read any source:\n" + "\n".join(errors))
        return 0

    if first_run:
        seen.update(l["id"] for l in listings)
        save_seen(seen)
        note = f" (⚠️ some sources failed: {'; '.join(errors)})" if errors else ""
        tg_text(
            f"✅ Bot initialized. Tracking {len(listings)} current listings{note}. "
            f"From now on you'll only get NEW ones."
        )
        return 0

    new_items = [l for l in listings if l["id"] not in seen]
    print(f"{len(new_items)} new.")
    for listing in new_items[:MAX_SENDS_PER_RUN]:
        send_listing(listing)
        time.sleep(1.5)

    seen.update(l["id"] for l in listings)
    save_seen(seen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
