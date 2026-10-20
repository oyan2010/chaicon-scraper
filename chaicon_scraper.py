"""
Chaicon Buyer Requests Scraper
Reusable - pass any keyword(s) as command line arguments
Usage: python chaicon_scraper.py shirts surgical
"""

import csv
import time
import os
import re
import sys
from seleniumbase import SB


class ChaiconScraper:
    def __init__(self, output_file=None):
        if output_file is None:
            output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manufacturers.csv")
        self.output_file = output_file
        self.sb = None
        self.data = []
        self.seen_phones = set()  # Track unique phone numbers

    def get_request_urls_from_page(self):
        urls = []
        time.sleep(5)
        try:
            page_source = self.sb.get_page_source()
            patterns = [
                r'chaicon\.com/requests/([a-zA-Z0-9_-]+)',
                r'/requests/([a-zA-Z0-9_-]+)',
            ]
            seen_slugs = set()
            for pattern in patterns:
                matches = re.findall(pattern, page_source)
                for slug in matches:
                    if slug not in seen_slugs and len(slug) > 5:
                        seen_slugs.add(slug)
                        full_url = f"https://chaicon.com/requests/{slug}"
                        if full_url not in urls:
                            urls.append(full_url)
                if urls:
                    break
        except Exception as e:
            print(f"    Error parsing page: {e}")
        print(f"    Found {len(urls)} URLs")
        return urls

    def extract_request_details(self, max_retries=3):
        details = {
            "phone": "", "name": "", "product_needed": "",
            "category": "", "city": "", "image": "", "other_details": "",
            "posted_date": ""
        }
        for attempt in range(max_retries):
            try:
                time.sleep(5)
                page_source = self.sb.get_page_source()

                if "Just a moment" in page_source:
                    print(f"    Cloudflare blocked, retry...")
                    time.sleep(10)
                    continue

                match = re.search(r'<h4[^>]*class="[^"]*fw-bold[^"]*"[^>]*>([^<]+)</h4>', page_source)
                if match:
                    details["product_needed"] = match.group(1).strip()

                match = re.search(r'<p[^>]*class="[^"]*mb-4[^"]*"[^>]*>([^<]+)</p>', page_source)
                if match:
                    details["other_details"] = match.group(1).strip()

                match = re.search(r'Name:</strong>\s*([^<]+)', page_source)
                if match:
                    details["name"] = match.group(1).strip()

                match = re.search(r'Category:</strong>\s*([^<]+)', page_source)
                if match:
                    details["category"] = match.group(1).strip()

                match = re.search(r'City:</strong>\s*([^<]+)', page_source)
                if match:
                    details["city"] = match.group(1).strip()

                match = re.search(r'https://chaicon\.com/content/questioning/[^"\'<>]+\.webp', page_source)
                if match:
                    details["image"] = match.group(0)

                date_match = re.search(r'Posted on ([A-Z][a-z]{2} \d{2}, \d{4} \d{2}:\d{2} [AP]M)', page_source)
                if date_match:
                    details["posted_date"] = date_match.group(1).strip()

                phone_match = re.search(r'<a[^>]*href="tel:([^"]+)"[^>]*id="copyQuestionPhone"', page_source)
                if phone_match:
                    details["phone"] = phone_match.group(1).strip()
                else:
                    try:
                        self.sb.click("#revealQuestionPhone")
                        time.sleep(2)
                        phone_el = self.sb.find_element("a#copyQuestionPhone", timeout=3)
                        href = phone_el.get_attribute("href") or ""
                        details["phone"] = href.replace("tel:", "").strip()
                    except Exception:
                        pass

                break
            except Exception as e:
                print(f"    Error: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)
        return details

    def scrape_keyword(self, keyword, max_pages=10):
        base_url = f"https://chaicon.com/requests?search={keyword}"
        all_urls = []
        page = 1
        prev_page_urls = []
        page_size = 30

        print(f"\n=== Scraping: {keyword} ===")

        while page <= max_pages:
            url = base_url if page == 1 else f"{base_url}&page={page}"
            print(f"  Page {page}")

            for cf_attempt in range(3):
                try:
                    self.sb.open(url)
                    time.sleep(8)
                    page_source = self.sb.get_page_source()
                    if "Just a moment" in page_source:
                        print(f"    Cloudflare challenge, attempt {cf_attempt + 1}/3")
                        time.sleep(15)
                        continue
                    break
                except Exception as e:
                    print(f"    Error: {e}")
                    time.sleep(10)

            urls = self.get_request_urls_from_page()
            if not urls:
                print(f"    No more requests")
                break
            if len(urls) < page_size:
                print(f"    Last page (only {len(urls)})")
                all_urls.extend(urls)
                break
            if urls[:5] == prev_page_urls[:5]:
                print(f"    Loop detected - done")
                break
            prev_page_urls = urls[:5]
            all_urls.extend(urls)
            page += 1

        print(f"  Total URLs: {len(all_urls)}")

        for i, url in enumerate(all_urls):
            print(f"  {i+1}/{len(all_urls)}", end="")
            try:
                self.sb.open(url)
                time.sleep(5)
                details = self.extract_request_details()
                details["product_needed"] = details["product_needed"] or keyword.title()
                phone = details.get("phone", "")
                name = details.get("name", "")[:20]
                date = details.get("posted_date", "")
                print(f" name={name}, phone={phone[:15]}, date={date}")
                self.data.append(details)
                self.save_to_csv()
            except Exception as e:
                print(f" Error: {e}")
            time.sleep(1)

        return self.data

    def load_existing_phones(self):
        """Load existing phone numbers from CSV to avoid duplicates"""
        if not os.path.exists(self.output_file):
            return
        with open(self.output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                phone = row.get("Phone Number", "").strip()
                if phone:
                    self.seen_phones.add(phone)

    def is_duplicate(self, item):
        phone = item.get("phone", "").strip()
        if phone and phone in self.seen_phones:
            return True
        if phone:
            self.seen_phones.add(phone)
        return False

    def save_to_csv(self):
        if not self.data:
            return
        fieldnames = ["Phone Number", "Name", "Product Needed", "Category", "Image", "Posted Date", "Other Details"]
        try:
            self.load_existing_phones()
            new_records = [item for item in self.data if not self.is_duplicate(item)]
            if not new_records:
                print(f"    All duplicates, skipped")
                self.data = []
                return

            file_exists = os.path.exists(self.output_file)
            with open(self.output_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                for item in new_records:
                    writer.writerow({
                        "Phone Number": item.get("phone", ""),
                        "Name": item.get("name", ""),
                        "Product Needed": item.get("product_needed", ""),
                        "Category": item.get("category", ""),
                        "Image": item.get("image", ""),
                        "Posted Date": item.get("posted_date", ""),
                        "Other Details": item.get("other_details", "")[:500] if item.get("other_details") else ""
                    })
            print(f"    Saved {len(new_records)} new records")
            self.data = []
        except Exception as e:
            print(f"    CSV Error: {e}")

    def run(self, keywords):
        try:
            with SB(uc=True, headless=False, test=True) as sb:
                self.sb = sb
                print("SeleniumBase initialized")
                for keyword in keywords:
                    self.scrape_keyword(keyword)
                print("\n=== Complete ===")
        except Exception as e:
            print(f"Error: {e}")


def main():
    keywords = sys.argv[1:] if len(sys.argv) > 1 else ["shirts", "surgical"]
    print(f"Keywords: {keywords}")
    scraper = ChaiconScraper()
    scraper.run(keywords)


if __name__ == "__main__":
    main()