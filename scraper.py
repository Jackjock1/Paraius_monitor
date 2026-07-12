"""
Pararius -> Telegram notifier (Amsterdam)
- Checks Pararius search pages, sends ONLY new listings to a Telegram chat/channel.
- Remembers what it already sent in seen.json (committed back to the repo by
  the GitHub Actions workflow), so restarts NEVER cause repeated posts.
- First run: silently marks all current listings as seen (no flood).
"""

import json
import os
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ----------------- SETTINGS (edit these) -----------------
SEARCH_URLS = [
    # Amsterdam, max price 1600 EUR. Change/add filters by building the URL
    # on pararius.com and pasting it here. You can add multiple URLs.
    "https://www.pararius.com/apartments/amsterdam/0-1600",
]
MAX_SENDS_PER_RUN = 10      # safety cap so it can never flood the chat
SEEN_FILE = Path("seen.json")
MAX_SEEN_STORED = 3000      # keep file small
# ----------------------------------------------------------

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,nl;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set) -> None:
    # keep only the most recent N ids (order doesn't matter for dedup)
    trimmed = list(seen)[-MAX_SEEN_STORED:]
    SEEN_FILE.write_text(json.dumps(trimmed, indent=0))


def fetch_listings() -> list[dict]:
    """Return list of {id, url, title, price, address, image}."""
    listings = []
    for search_url in SEARCH_URLS:
        resp = requests.get(search_url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            print(f"WARN: {search_url} returned HTTP {resp.status_code}")
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select("section.listing-search-item"):
            link = item.select_one("a.listing-search-item__link--title")
            if not link:
                continue
            url = "https://www.pararius.com" + link.get("href", "")
            price_el = item.select_one(".listing-search-item__price")
            addr_el = item.select_one(".listing-search-item__sub-title")
            img_el = item.select_one("img")
            listings.append(
                {
                    "id": url,  # the listing URL is a stable unique id
                    "url": url,
                    "title": link.get_text(strip=True),
                    "price": price_el.get_text(strip=True) if price_el else "N/A",
                    "address": addr_el.get_text(strip=True) if addr_el else "",
                    "image": img_el.get("src") if img_el else None,
                }
            )
    return listings


def send_telegram(listing: dict) -> None:
    caption = (
        f"🏠 {listing['title']}\n"
        f"💶 {listing['price']}\n"
        f"📍 {listing['address']}\n"
        f"🔗 {listing['url']}"
    )
    if listing["image"] and listing["image"].startswith("http"):
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id": CHAT_ID, "photo": listing["image"], "caption": caption},
            timeout=30,
        )
        if r.ok:
            return
        # photo failed (dead url etc.) -> fall through to plain message
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": caption},
        timeout=30,
    )


def main() -> int:
    first_run = not SEEN_FILE.exists()
    seen = load_seen()

    listings = fetch_listings()
    if not listings:
        print("No listings parsed (site blocked or layout changed). Nothing sent.")
        # Do NOT wipe seen.json on failure — keeps dedup intact.
        return 0

    if first_run:
        # Seed silently: mark everything as seen, send nothing.
        seen.update(l["id"] for l in listings)
        save_seen(seen)
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": f"✅ Bot initialized. Tracking {len(listings)} current "
                        f"listings. From now on you'll only get NEW ones.",
            },
            timeout=30,
        )
        return 0

    new_items = [l for l in listings if l["id"] not in seen]
    print(f"Found {len(listings)} listings, {len(new_items)} new.")

    for listing in new_items[:MAX_SENDS_PER_RUN]:
        send_telegram(listing)
        time.sleep(1.5)  # respect Telegram rate limits

    # Mark ALL current listings as seen (even beyond the send cap,
    # so a huge batch never causes repeats later).
    seen.update(l["id"] for l in listings)
    save_seen(seen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
