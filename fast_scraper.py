"""
Fast Chaicon Buyer Requests Scraper (BeautifulSoup + requests)
No Selenium needed — Cloudflare protection has been removed.
Usage: python fast_scraper.py shirts surgical tshirts
"""

import csv
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            resp = SESSION.get(url, timeout=15)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            return None


def parse_card(card):
    a_tag = card.select_one('a[href*="/requests/"]')
    if not a_tag:
        return None
    href = a_tag.get('href', '')
    full_url = 'https://chaicon.com' + href if href.startswith('/') else href

    title_el = card.select_one('h5')
    title = title_el.get_text(strip=True) if title_el else ''

    name_el = card.select_one('.buyer-name')
    name = name_el.get_text(strip=True) if name_el else ''

    city_el = card.select_one('.city-name')
    city = city_el.get_text(strip=True).strip('() ') if city_el else ''

    time_el = card.select_one('.fa-clock')
    days_ago = ''
    if time_el and time_el.parent:
        full_text = time_el.parent.get_text(strip=True)
        m = re.search(r'(\d+\s*days?\s*ago)', full_text)
        if m:
            days_ago = m.group(1)

    img_el = card.select_one('.left-img img')
    image = img_el.get('src', '') if img_el else ''
    if image and not image.startswith('http'):
        image = 'https://chaicon.com' + image

    is_old = 'old-request' in card.get('class', [])

    if not title:
        return None

    return {
        'url': full_url,
        'product_needed': title,
        'name': name,
        'city': city,
        'days_ago': days_ago,
        'image': image,
        'is_old': is_old,
    }


def scrape_listing_page(keyword, page=1):
    url = f'https://chaicon.com/requests?search={keyword}'
    if page > 1:
        url += f'&page={page}'
    html = fetch(url)
    if not html:
        return []
    soup = BeautifulSoup(html, 'html.parser')
    cards = soup.select('div.card.mb-1')
    results = []
    for card in cards:
        item = parse_card(card)
        if item:
            results.append(item)
    return results


def scrape_all_listings(keyword, max_pages=10):
    all_items = []
    for page in range(1, max_pages + 1):
        items = scrape_listing_page(keyword, page)
        if not items:
            break
        seen_urls = {i['url'] for i in all_items}
        new = [i for i in items if i['url'] not in seen_urls]
        if not new:
            break
        all_items.extend(new)
        print(f"  Page {page}: {len(new)} requests (total: {len(all_items)})")
        time.sleep(0.5)
    return all_items


def scrape_detail(item):
    html = fetch(item['url'])
    if not html:
        return item
    soup = BeautifulSoup(html, 'html.parser')

    phone = ''
    phone_el = soup.select_one('a#copyQuestionPhone')
    if phone_el:
        href = phone_el.get('href', '')
        phone = href.replace('tel:', '').strip()
    if not phone:
        phone_el = soup.select_one('a[href^="tel:"]')
        if phone_el:
            href = phone_el.get('href', '')
            phone = href.replace('tel:', '').strip()

    posted_date = ''
    date_el = soup.find('div', class_='text-muted small mb-3')
    if date_el:
        txt = date_el.get_text(strip=True)
        m = re.search(r'Posted on (.+)', txt)
        if m:
            posted_date = m.group(1).strip()

    other_details = ''
    desc_el = soup.select_one('p.mb-4')
    if desc_el:
        other_details = desc_el.get_text(strip=True)

    category = ''
    cat_match = re.search(r'Category:</strong>\s*([^<]+)', html)
    if cat_match:
        category = cat_match.group(1).strip()

    item['phone'] = phone
    item['posted_date'] = posted_date
    item['other_details'] = other_details
    item['category'] = item.get('category', '') or category
    return item


def save_to_csv(items, output_file):
    fieldnames = ['Phone Number', 'Name', 'Product Needed', 'Days Ago', 'Posted Date', 'Category', 'City', 'Image', 'Other Details']
    seen_phones = set()
    if os.path.exists(output_file):
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                p = row.get('Phone Number', '').strip()
                if p:
                    seen_phones.add(p)

    new_count = 0
    file_exists = os.path.exists(output_file)
    with open(output_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for item in items:
            phone = item.get('phone', '').strip()
            if not phone or phone in seen_phones:
                continue
            seen_phones.add(phone)
            writer.writerow({
                'Phone Number': phone,
                'Name': item.get('name', ''),
                'Product Needed': item.get('product_needed', ''),
                'Days Ago': item.get('days_ago', ''),
                'Posted Date': item.get('posted_date', ''),
                'Category': item.get('category', ''),
                'City': item.get('city', ''),
                'Image': item.get('image', ''),
                'Other Details': item.get('other_details', '')[:500],
            })
            new_count += 1
    return new_count


def main():
    keywords = sys.argv[1:] if len(sys.argv) > 1 else ['']
    output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'manufacturers')
    output_file = output_file+f"_{str(keywords[0])}.csv"
    all_items = []

    print(f"Output: {output_file}")
    print(f"Keywords: {keywords}")

    start = time.time()

    for kw in keywords:
        print(f"\n=== Scraping: {kw} ===")
        items = scrape_all_listings(kw, max_pages=10)
        print(f"  Total found: {len(items)}")
        all_items.extend(items)

    print(f"\n=== Fetching details for {len(all_items)} requests ===")
    enriched = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        fut_map = {pool.submit(scrape_detail, item): item for item in all_items}
        for i, fut in enumerate(as_completed(fut_map), 1):
            item = fut.result()
            enriched.append(item)
            name = item.get('name', '')[:15]
            phone = item.get('phone', '')[:15]
            date = item.get('posted_date', '')
            print(f"  {i}/{len(all_items)} name={name} phone={phone} date={date}")
    new = save_to_csv(enriched, output_file)
    elapsed = time.time() - start
    print(f"\n=== Done in {elapsed:.1f}s ===")
    print(f"  Total collected: {len(enriched)}")
    print(f"  New saved: {new}")
    print(f"  File: {output_file}")


if __name__ == '__main__':
    main()
