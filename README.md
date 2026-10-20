# Chaicon Buyer Request Scraper & Lead Generation Suite 📊🔍

An enterprise-ready lead generation and data scraping desktop tool built with **PyQt5**, **SeleniumBase**, and **SQLite**. Designed to automate discovery, scraping, and export of buyer requests and manufacturer leads from Chaicon with persistent task queues and PDF/CSV reporting.

---

## 🚀 Key Features

- **Automated Scraping Engine**: Headless / GUI browser automation via `SeleniumBase` (supporting undetected Chrome mode) to bypass complex protections and fetch buyer requests.
- **Persistent Task Queue**: Built on an SQLite database (`WAL` journal mode) to safely manage queued, processing, and completed scrape tasks.
- **Interactive PyQt5 Dashboard**:
  - Live task status tracker and URL progress monitoring.
  - Real-time logging console with auto-scrolling terminal window.
  - Data table browser with search, filtering, and detail previews.
- **Export Capabilities**:
  - Export structured lead datasets to CSV and Excel.
  - Generate formatted PDF reports with `FPDF2`.

---

## 🛠️ Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/oyan2010/chaicon-scraper.git
   cd chaicon-scraper
   ```

2. **Set up a virtual environment**:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the Application**:
   - **GUI Mode**:
     ```bash
     python chaicon_gui.py
     ```
   - **CLI / Fast Scraper**:
     ```bash
     python fast_scraper.py
     ```

---

## 📦 Tech Stack

- **GUI**: PyQt5
- **Browser Automation**: SeleniumBase (Undetected ChromeDriver)
- **Database**: SQLite3
- **PDF Generation**: FPDF2
- **Language**: Python 3.9+
