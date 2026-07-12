"""
GITHUB TEST: can GitHub's servers scrape Pararius using the Chrome disguise?
- One-shot, manual trigger only. No seen.json, no loop.
- Sends a status message + the first 10 current postings to Telegram.
- Safe to run while your laptop bot is running (it never touches its memory).
"""

import os
import sys
import time

import requests  # Telegram only
from bs4 import BeautifulSoup
from curl_cffi import requests as browser_requests

PARARIUS_URL = "https://www.pararius.com/apartments/amsterdam"

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


def tg_text(text: str) -> None:
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True},
        timeout=30,
    )


def send_listing(l: dict) -> None:
    caption = (
        f"🧪 GITHUB TEST\n"
        f"🏠 {l['title']}\n"
        f"💶 {l['price']}\n"
        f"📍 {l['address']}\n"
        f"🔗 {l['url']}"
    )
    if l.get("image") and str(l["image"]).startswith("http"):
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id": CHAT_ID, "photo": l["image"], "caption": caption},
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
    try:
        resp = browser_requests.get(PARARIUS_URL, impersonate="chrome", timeout=30)
    except Exception as e:
        tg_text(f"🧪 GITHUB TEST result: connection error ({type(e).__name__})")
        return 0

    if resp.status_code != 200:
        tg_text(
            f"🧪 GITHUB TEST result: Pararius returned HTTP {resp.status_code} "
            f"— GitHub's servers are still blocked. Keep using the laptop bot."
        )
        return 0

    soup = BeautifulSoup(resp.text, "html.parser")
    listings = []
    for item in soup.select("section.listing-search-item"):
        link = item.select_one("a.listing-search-item__link--title")
        if not link or not link.get("href"):
            continue
        href = link["href"]
        price_el = item.select_one(".listing-search-item__price")
        addr_el = item.select_one(".listing-search-item__sub-title")
        img_el = item.select_one("img")
        listings.append(
            {
                "title": link.get_text(strip=True),
                "url": href if href.startswith("http") else "https://www.pararius.com" + href,
                "price": price_el.get_text(strip=True) if price_el else "N/A",
                "address": addr_el.get_text(strip=True) if addr_el else "",
                "image": (img_el.get("src") or img_el.get("data-src")) if img_el else None,
            }
        )

    print(f"HTTP 200, parsed {len(listings)} listings")
    for l in listings[:10]:
        print(f"  - {l['title']} | {l['price']} | {l['address']}")

    if not listings:
        tg_text(
            "🧪 GITHUB TEST result: HTTP 200 but 0 listings parsed "
            "(Cloudflare challenge page or layout issue)."
        )
        return 0

    tg_text(
        f"🧪 GITHUB TEST result: SUCCESS ✅ — GitHub can scrape Pararius! "
        f"Found {len(listings)} listings. Sending the first 10:"
    )
    for l in listings[:10]:
        send_listing(l)
        time.sleep(1.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
