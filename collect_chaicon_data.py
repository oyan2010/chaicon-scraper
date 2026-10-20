import csv
import os
import re
import time
from bs4 import BeautifulSoup
import requests

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}


def get_soup(url):
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None


def extract_requests(search_term, category):
    url = f"https://chaicon.com/requests?search={search_term}"
    soup = get_soup(url)

    if not soup:
        return []

    requests_list = []

    cards = soup.find_all('div', class_='card')

    for card in cards:
        try:
            title_elem = card.find('h5')
            title = title_elem.get_text(strip=True) if title_elem else ""

            name_elem = card.find('span', class_='buyer-name')
            name = name_elem.get_text(strip=True) if name_elem else ""

            city_elem = card.find('span', class_='my-text-color5')
            city = ""
            if city_elem:
                city_text = city_elem.get_text(strip=True)
                city = city_text.strip('() ')

            link_elem = card.find('a', href=True)
            detail_url = ""
            if link_elem and '/requests/' in link_elem.get('href', ''):
                detail_url = "https://chaicon.com" + link_elem.get('href')

            if title and name:
                requests_list.append({
                    'name': name,
                    'product': title,
                    'city': city,
                    'category': category,
                    'detail_url': detail_url
                })
        except Exception as e:
            print(f"Error parsing card: {e}")
            continue

    return requests_list


def get_request_details(url):
    soup = get_soup(url)
    if not soup:
        return {}

    details = {}

    desc_div = soup.find('div', class_='card')
    if desc_div:
        desc_text = desc_div.get_text(separator=' ', strip=True)
        details['description'] = desc_text

    buyer_info = soup.find('div', text=re.compile('Buyer Information', re.IGNORECASE))
    if buyer_info:
        parent = buyer_info.find_parent('div')
        if parent:
            info_text = parent.get_text(separator=' ', strip=True)

            name_match = re.search(r'Name:\s*([^\n]+)', info_text)
            if name_match:
                details['name'] = name_match.group(1).strip()

            cat_match = re.search(r'Category:\s*([^\n]+)', info_text)
            if cat_match:
                details['buyer_category'] = cat_match.group(1).strip()

            city_match = re.search(r'City:\s*([^\n]+)', info_text)
            if city_match:
                details['city'] = city_match.group(1).strip()

    images = []
    img_tags = soup.find_all('img')
    for img in img_tags:
        src = img.get('src', '')
        if src and 'upload' in src.lower():
            images.append(src)

    if images:
        details['images'] = images

    return details


def main():
    all_requests = []

    print("Collecting shirt requests...")
    shirt_requests = extract_requests('shirts', 'Shirt')
    print(f"Found {len(shirt_requests)} shirt requests")
    all_requests.extend(shirt_requests)

    print("Collecting tshirt requests...")
    tshirt_requests = extract_requests('t shirt', 'Shirt')
    print(f"Found {len(tshirt_requests)} tshirt requests")
    all_requests.extend(tshirt_requests)

    print("Collecting surgical instrument requests...")
    surgical_requests = extract_requests('surgical', 'Surgical Instrument')
    print(f"Found {len(surgical_requests)} surgical requests")
    all_requests.extend(surgical_requests)

    print("Collecting medical instrument requests...")
    medical_requests = extract_requests('medical instrument', 'Surgical Instrument')
    print(f"Found {len(medical_requests)} medical requests")
    all_requests.extend(medical_requests)

    unique_requests = []
    seen = set()
    for req in all_requests:
        key = (req['name'], req['product'])
        if key not in seen:
            seen.add(key)
            unique_requests.append(req)

    print(f"\nTotal unique requests: {len(unique_requests)}")

    print("\nGetting detailed information for each request...")
    for i, req in enumerate(unique_requests):
        print(f"Processing {i+1}/{len(unique_requests)}: {req['product'][:50]}...")
        if req.get('detail_url'):
            details = get_request_details(req['detail_url'])
            req.update(details)
        time.sleep(0.5)

    csv_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'manufacturers.csv')
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Phone Number', 'Name', 'Product Needed', 'Category', 'Image', 'Other Details'])

        for req in unique_requests:
            phone = "Login required"
            images = req.get('images', [])
            image = images[0] if images else ""

            other_details = []
            if req.get('description'):
                other_details.append(f"Description: {req['description'][:200]}")
            if req.get('buyer_category'):
                other_details.append(f"Buyer Type: {req['buyer_category']}")
            if req.get('city'):
                other_details.append(f"City: {req['city']}")

            other = " | ".join(other_details)

            writer.writerow([
                phone,
                req.get('name', ''),
                req.get('product', ''),
                req.get('category', ''),
                image,
                other
            ])

    print(f"\nCSV saved to: {csv_file}")
    print(f"Total records: {len(unique_requests)}")


if __name__ == "__main__":
    main()
