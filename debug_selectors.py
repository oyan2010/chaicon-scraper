"""Debug CG selectors"""
import time
from seleniumbase import SB

with SB(uc=True, headless=False, test=True) as sb:
    sb.open("https://chaicon.com/requests?search=shirts")
    time.sleep(4)

    # Method 1: Get all links with full href in the page
    all_links = sb.find_elements("a")
    request_urls = []
    for link in all_links:
        href = link.get_attribute("href") or ""
        if "chaicon.com/requests/" in href and href != "https://chaicon.com/requests" and "chaicon.com/requests?" not in href:
            slug = href.rstrip("/").split("/")[-1]
            if slug and slug not in [u.rstrip("/").split("/")[-1] for u in request_urls]:
                request_urls.append(href)
    print(f"Total request URLs via 'a' tags: {len(request_urls)}")
    for u in request_urls[:5]:
        print(f"  {u}")

    # Method 2: Try selector without quotes
    try:
        els = sb.find_elements("a.text-center")
        print(f"\nSelector a.text-center: {len(els)}")
        for e in els[:3]:
            print(f"  href: {e.get_attribute('href')}")
    except Exception as ex:
        print(f"Error: {ex}")

    # Method 3: Get cards and find links
    cards = sb.find_elements("div.card.mb-1")
    print(f"\nCards: {len(cards)}")
