"""Chaicon Buyer Request Scraper - GUI Edition"""
import csv, json, os, sys, time, sqlite3, threading, traceback, urllib.parse
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QTabWidget, QTextEdit, QMessageBox, QGroupBox, QStatusBar,
    QComboBox, QDialog, QInputDialog, QMenu, QProgressBar, QFileDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject
from PyQt5.QtGui import QTextCursor
from seleniumbase import SB
from fpdf import FPDF

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chaicon_tasks.db")
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scraper_debug.log")


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        conn.execute("ALTER TABLE results ADD COLUMN posted_date TEXT")
    except Exception:
        pass
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            status TEXT DEFAULT 'queued',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            completed_at TEXT,
            total_urls INTEGER DEFAULT 0,
            processed_urls INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS task_urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER, url TEXT,
            page_number INTEGER, status TEXT DEFAULT 'pending',
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        );
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER, url TEXT,
            phone TEXT, name TEXT, product_needed TEXT,
            category TEXT, city TEXT, image TEXT,
            posted_date TEXT,
            other_details TEXT,
            scraped_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        );
    """)
    conn.commit()
    return conn


def safe_text(value, limit=None):
    """Safely convert a DB value to string, handling None."""
    if value is None:
        return ""
    text = str(value)
    if limit and len(text) > limit:
        return text[:limit]
    return text


def export_rows_to_csv(rows, path):
    """Consolidated CSV export helper."""
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(["Phone", "Name", "Product", "Category", "City", "Posted Date", "Image", "Details"])
        for r in rows:
            w.writerow([
                r["phone"], r["name"], r["product_needed"],
                r["category"], r["city"], r["posted_date"], r["image"], r["other_details"]
            ])
    return len(rows)


def delete_task_data(db, tid):
    """Consolidated cascade delete for a task."""
    db.execute("DELETE FROM results WHERE task_id=?", (tid,))
    db.execute("DELETE FROM task_urls WHERE task_id=?", (tid,))
    db.execute("DELETE FROM tasks WHERE id=?", (tid,))
    db.commit()


def deduplicate_rows(rows):
    """Remove duplicate rows based on phone+name+product key."""
    seen = set()
    unique = []
    for r in rows:
        key = (safe_text(r["phone"]).lower(), safe_text(r["name"]).lower(), safe_text(r["product_needed"]).lower())
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def export_rows_to_pdf(rows, path, title="Chaicon Results"):
    """Export rows to a PDF file with deduplication."""
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, title, ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Total: {len(rows)} records | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align="C")
    pdf.ln(5)

    # Table header
    col_widths = [35, 35, 50, 35, 30, 95]  # Phone, Name, Product, Category, City, Details
    headers = ["Phone", "Name", "Product", "Category", "City", "Details"]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(44, 62, 80)
    pdf.set_text_color(255, 255, 255)
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 7, h, border=1, fill=True, align="C")
    pdf.ln()

    # Table rows
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(0, 0, 0)
    fill = False
    for r in rows:
        if fill:
            pdf.set_fill_color(240, 240, 240)
        else:
            pdf.set_fill_color(255, 255, 255)

        vals = [
            safe_text(r["phone"], 20),
            safe_text(r["name"], 20),
            safe_text(r["product_needed"], 35),
            safe_text(r["category"], 25),
            safe_text(r["city"], 20),
            safe_text(r["other_details"], 70),
        ]
        for i, v in enumerate(vals):
            pdf.cell(col_widths[i], 6, v, border=1, fill=True)
        pdf.ln()
        fill = not fill

    pdf.output(path)
    return len(rows)


# --- Signals holder ---
class WorkerSignals(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int, int)
    finished = pyqtSignal(int)
    error = pyqtSignal(str)


# --- Scraper Worker (single-threaded, sequential tasks) ---
class ScraperWorker(QThread):
    def __init__(self, task_id, keyword):
        super().__init__()
        self.task_id = task_id
        self.keyword = keyword
        self.signals = WorkerSignals()
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    @property
    def is_stopped(self):
        return self._stop_event.is_set()

    def log(self, msg):
        self.signals.log.emit(f"[{self.keyword}] {msg}")

    def debug_log(self, msg):
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] T{self.task_id} {msg}\n")
        except Exception:
            pass

    def run(self):
        self.debug_log("=== WORKER STARTED ===")
        db = get_db()
        try:
            db.execute("UPDATE tasks SET status='running' WHERE id=?", (self.task_id,))
            db.commit()
            self.log("Starting...")

            encoded_kw = urllib.parse.quote(self.keyword)
            all_urls = []
            page = 1
            prev_id = ""
            processed = 0

            self.debug_log(f"Phase 1: Collecting URLs for '{self.keyword}' (encoded: '{encoded_kw}')")
            with SB(uc=True, headless=False) as sb:
                self.debug_log("SB context opened")
                # Phase 1: Collect URLs
                first_urls = set()
                while page <= 10 and not self.is_stopped:
                    url = f"https://chaicon.com/requests?search={encoded_kw}"
                    if page > 1:
                        url += f"&page={page}"

                    self.debug_log(f"Page {page}: {url}")
                    self.log(f"Page {page}...")
                    try:
                        sb.open(url)
                        time.sleep(3)
                        self.debug_log(f"Page loaded, title: {sb.get_title()}")
                    except Exception as e:
                        self.debug_log(f"Nav error: {e}")
                        self.log(f"Nav error: {e}")
                        break

                    # Check cards exist
                    try:
                        cards = sb.find_elements("div.card.mb-1")
                        self.debug_log(f"Found {len(cards)} cards")
                        if not cards:
                            self.debug_log("No cards found, breaking")
                            break
                        curr = cards[0].text[:100]
                        self.debug_log(f"First card text: '{curr[:60]}'")
                        if prev_id and curr == prev_id:
                            self.log(f"End at page {page}")
                            break
                        prev_id = curr
                    except Exception as ex:
                        self.debug_log(f"Card check error: {ex}")
                        break

                    # Extract URLs via ALL anchor tags
                    page_urls = []
                    try:
                        all_anchors = sb.find_elements("a")
                        self.debug_log(f"Found {len(all_anchors)} total <a> tags")
                        seen_slugs = {u.rstrip("/").split("/")[-1] for u in all_urls}
                        for el in all_anchors:
                            href = el.get_attribute("href") or ""
                            if "chaicon.com/requests/" in href and "/requests/" in href:
                                slug = href.rstrip("/").split("/")[-1]
                                if slug and slug not in seen_slugs and "?" not in slug:
                                    page_urls.append(href)
                                    seen_slugs.add(slug)
                    except Exception as ex:
                        self.debug_log(f"URL extraction error: {ex}")
                        try:
                            link_els = sb.find_elements("a.text-center")
                            self.debug_log(f"Fallback: found {len(link_els)} a.text-center")
                            for el in link_els:
                                href = el.get_attribute("href") or ""
                                if "/requests/" in href and "chaicon.com/requests/" in href:
                                    slug = href.rstrip("/").split("/")[-1]
                                    if slug and slug not in [u.rstrip("/").split("/")[-1] for u in all_urls]:
                                        page_urls.append(href)
                        except Exception as ex2:
                            self.debug_log(f"Fallback also failed: {ex2}")

                    self.debug_log(f"Found {len(page_urls)} URLs on this page")
                    if not page_urls:
                        self.debug_log("No URLs found, breaking")
                        break

                    if page == 1:
                        first_urls = set(page_urls)
                    elif page > 1:
                        overlap = len([u for u in page_urls if u in first_urls])
                        self.debug_log(f"Overlap with page 1: {overlap}/{len(page_urls)}")
                        if overlap >= len(page_urls) * 0.7:
                            self.log(f"Wrapped at page {page}")
                            break

                    all_urls.extend(page_urls)
                    self.log(f"Page {page}: {len(page_urls)} URLs (total: {len(all_urls)})")
                    page += 1

                self.debug_log(f"Phase 1 complete: {len(all_urls)} total URLs")

                # Save URLs
                for u in all_urls:
                    db.execute("INSERT OR IGNORE INTO task_urls VALUES(NULL,?,?,0,'pending')", (self.task_id, u))
                db.execute("UPDATE tasks SET total_urls=? WHERE id=?", (len(all_urls), self.task_id))
                db.commit()

                # Resume check
                done = {r["url"] for r in db.execute("SELECT url FROM results WHERE task_id=?", (self.task_id,))}
                todo = [u for u in all_urls if u not in done]
                self.log(f"Phase 2: {len(todo)} to scrape ({len(done)} already done)")

                # Phase 2: Scrape details
                self.debug_log(f"Phase 2: {len(todo)} URLs to scrape")
                for idx, req_url in enumerate(todo):
                    if self.is_stopped:
                        break

                    self.log(f"({idx+1}/{len(todo)})")
                    self.debug_log(f"Scraping {req_url}")
                    try:
                        sb.open(req_url)
                        time.sleep(2.5)
                        self.debug_log(f"Page title: {sb.get_title()[:60]}")

                        d = {"url": req_url, "phone": "", "name": "", "product_needed": "",
                             "category": "", "city": "", "image": "", "other_details": ""}

                        try:
                            d["product_needed"] = sb.find_element("h4.fw-bold.mb-2", timeout=4).text
                        except Exception:
                            pass
                        try:
                            d["other_details"] = sb.find_element("p.mb-4", timeout=4).text
                            self.debug_log(f"Description found: {d['other_details'][:40]}")
                        except Exception:
                            self.debug_log("No description found")
                        try:
                            for li in sb.find_elements("ul.list-unstyled.small li.mb-2"):
                                t = li.text
                                if t.startswith("Name:"):
                                    d["name"] = t.replace("Name:", "").strip()
                                elif t.startswith("Category:"):
                                    d["category"] = t.replace("Category:", "").strip()
                                elif t.startswith("City:"):
                                    d["city"] = t.replace("City:", "").strip()
                            self.debug_log(f"Name: {d['name']}, City: {d['city']}")
                        except Exception:
                            self.debug_log("No info list found")
                        try:
                            img = sb.find_element("div.mb-3 img.img-fluid.rounded", timeout=3)
                            d["image"] = img.get_attribute("src") or ""
                            self.debug_log(f"Image: {d['image'][:60]}")
                        except Exception:
                            pass

                        # Phone
                        try:
                            phone_el = sb.find_element("a#copyQuestionPhone", timeout=2)
                            href = phone_el.get_attribute("href") or ""
                            d["phone"] = href.replace("tel:", "").strip()
                        except Exception:
                            self.debug_log("Clicking reveal phone...")
                            try:
                                sb.click("#revealQuestionPhone")
                                time.sleep(2)
                                phone_el = sb.find_element("a#copyQuestionPhone", timeout=3)
                                href = phone_el.get_attribute("href") or ""
                                d["phone"] = href.replace("tel:", "").strip()
                                self.debug_log(f"Phone after reveal: {d['phone']}")
                            except Exception:
                                self.debug_log("Reveal button or phone element not found")

                        self.debug_log(f"Result: phone={d['phone']}, name={d['name']}")
                        db.execute("""INSERT INTO results(task_id,url,phone,name,product_needed,category,city,image,other_details)
                                      VALUES(?,?,?,?,?,?,?,?,?)""",
                                   (self.task_id, req_url, d["phone"], d["name"], d["product_needed"],
                                    d["category"], d["city"], d["image"], d["other_details"][:500]))
                        db.commit()
                        processed += 1
                        self.signals.progress.emit(self.task_id, processed, len(todo))
                    except Exception as e:
                        self.debug_log(f"Phase 2 error: {traceback.format_exc()[:300]}")
                        self.log(f"Error: {str(e)[:100]}")
                        continue
                    time.sleep(0.5)

        except Exception as e:
            self.debug_log(f"FATAL: {traceback.format_exc()}")
            self.signals.error.emit(f"[{self.keyword}] Fatal: {traceback.format_exc()}")
        finally:
            st = "completed" if not self.is_stopped else "paused"
            try:
                db.execute("UPDATE tasks SET status=?, completed_at=datetime('now','localtime'), processed_urls=? WHERE id=?",
                           (st, processed, self.task_id))
                db.commit()
            except Exception:
                pass
            finally:
                db.close()
            self.signals.finished.emit(self.task_id)
            self.log(f"Done ({st})")


# --- Detail Dialog ---
class TaskDetailDialog(QDialog):
    def __init__(self, task_id, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.setWindowTitle(f"Task #{task_id} Results")
        self.resize(1000, 600)
        self.setup_ui()
        self.load_data()

    def setup_ui(self):
        lo = QVBoxLayout()
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["Phone", "Name", "Product", "Category", "City", "Posted Date", "Details"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        lo.addWidget(self.table)
        btn = QPushButton("Export to CSV")
        btn.clicked.connect(self.export_csv)
        lo.addWidget(btn)
        self.setLayout(lo)

    def load_data(self):
        db = get_db()
        rows = db.execute("SELECT * FROM results WHERE task_id=? ORDER BY id", (self.task_id,)).fetchall()
        db.close()
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(safe_text(r["phone"])))
            self.table.setItem(i, 1, QTableWidgetItem(safe_text(r["name"])))
            self.table.setItem(i, 2, QTableWidgetItem(safe_text(r["product_needed"])))
            self.table.setItem(i, 3, QTableWidgetItem(safe_text(r["category"])))
            self.table.setItem(i, 4, QTableWidgetItem(safe_text(r["city"])))
            self.table.setItem(i, 5, QTableWidgetItem(safe_text(r["posted_date"])))
            self.table.setItem(i, 6, QTableWidgetItem(safe_text(r["other_details"], 100)))
        self.table.resizeColumnsToContents()

    def export_csv(self):
        default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"task_{self.task_id}.csv")
        path, ok = QInputDialog.getText(self, "Export", "Path:", text=default_path)
        if not ok or not path:
            return
        db = get_db()
        rows = db.execute("SELECT * FROM results WHERE task_id=?", (self.task_id,)).fetchall()
        db.close()
        count = export_rows_to_csv(rows, path)
        QMessageBox.information(self, "Done", f"Exported {count} rows")


# --- Main Window ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chaicon Scraper Pro")
        self.resize(1200, 800)
        self.workers = {}
        self._current_worker = None
        self._pending_tasks = []
        self.setup_ui()
        self.refresh_all()
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_queue)
        self.timer.start(3000)

    def setup_ui(self):
        c = QWidget()
        self.setCentralWidget(c)
        ml = QVBoxLayout(c)
        ml.setContentsMargins(10, 10, 10, 10)

        # Header
        h = QLabel("Chaicon Buyer Request Scraper")
        h.setStyleSheet("font-size:20px; font-weight:bold; color:#2c3e50;")
        ml.addWidget(h)

        # Input row
        il = QHBoxLayout()
        self.kw = QLineEdit()
        self.kw.setPlaceholderText("Keywords: shirts, tshirts, surgical (comma-separated)...")
        self.kw.setMinimumHeight(34)
        self.kw.setStyleSheet("font-size:14px; border:2px solid #3498db; border-radius:5px; padding:4px;")
        self.kw.returnPressed.connect(self.add_keyword)

        for txt, slot, color in [("+ Add", self.add_keyword, "#3498db"),
                                   (">> Start All Queued", self.start_all, "#27ae60"),
                                   ("Stop All", self.stop_all, "#e74c3c")]:
            b = QPushButton(txt)
            b.setMinimumHeight(34)
            b.setStyleSheet(f"font-weight:bold; background:{color}; color:white; border:none; border-radius:5px; padding:0 15px;")
            b.clicked.connect(slot)
            il.addWidget(b)
        il.insertWidget(0, self.kw, 2)
        ml.addLayout(il)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabBar::tab{padding:8px 18px;font-size:13px} QTabWidget::pane{border:1px solid #bdc3c7;border-radius:4px}")

        # Queue tab
        qt = QWidget()
        ql = QVBoxLayout()
        self.queue_tbl = QTableWidget()
        self.queue_tbl.setColumnCount(5)
        self.queue_tbl.setHorizontalHeaderLabels(["ID", "Keyword", "Status", "Progress", "Actions"])
        self.queue_tbl.horizontalHeader().setStretchLastSection(True)
        self.queue_tbl.setAlternatingRowColors(True)
        self.queue_tbl.setSelectionBehavior(QTableWidget.SelectRows)
        ql.addWidget(self.queue_tbl, 1)

        lg = QGroupBox("Activity Log")
        ll = QVBoxLayout()
        self.log_txt = QTextEdit()
        self.log_txt.setReadOnly(True)
        self.log_txt.setMaximumHeight(160)
        self.log_txt.setStyleSheet("font-family:Consolas;font-size:12px;background:#1e1e1e;color:#d4d4d4;")
        ll.addWidget(self.log_txt)
        lg.setLayout(ll)
        ql.addWidget(lg)
        qt.setLayout(ql)
        self.tabs.addTab(qt, "Queue & Running")

        # History tab
        ht = QWidget()
        hl = QVBoxLayout()
        self.hist_tbl = QTableWidget()
        self.hist_tbl.setColumnCount(6)
        self.hist_tbl.setHorizontalHeaderLabels(["ID", "Keyword", "Status", "URLs", "Done", "Completed"])
        self.hist_tbl.horizontalHeader().setStretchLastSection(True)
        self.hist_tbl.setAlternatingRowColors(True)
        self.hist_tbl.setSelectionBehavior(QTableWidget.SelectRows)
        self.hist_tbl.setContextMenuPolicy(Qt.CustomContextMenu)
        self.hist_tbl.customContextMenuRequested.connect(self.hist_menu)
        self.hist_tbl.doubleClicked.connect(self.view_results)
        hl.addWidget(self.hist_tbl, 1)

        bl = QHBoxLayout()
        for txt, slot, color in [("View Results", self.view_results, "#3498db"),
                                   ("Delete Selected", self.delete_task, "#e74c3c"),
                                   ("Export Selected (CSV)", self.export_selected, "#27ae60"),
                                   ("Merge All (PDF)", self.export_all_pdf, "#8e44ad")]:
            b = QPushButton(txt)
            b.setStyleSheet(f"font-weight:bold; background:{color}; color:white; border:none; border-radius:4px; padding:7px;")
            b.clicked.connect(slot)
            bl.addWidget(b)
        hl.addLayout(bl)
        ht.setLayout(hl)
        self.tabs.addTab(ht, "History")

        # Results tab
        rt = QWidget()
        rl = QVBoxLayout()
        fl = QHBoxLayout()
        fl.addWidget(QLabel("Task:"))
        self.task_combo = QComboBox()
        fl.addWidget(self.task_combo)
        fl.addWidget(QLabel("Filter:"))
        self.filter_inp = QLineEdit()
        self.filter_inp.setPlaceholderText("search phone/name...")
        fl.addWidget(self.filter_inp)
        fb = QPushButton("Apply")
        fb.clicked.connect(self.load_results)
        fl.addWidget(fb)
        rl.addLayout(fl)

        self.res_tbl = QTableWidget()
        self.res_tbl.setColumnCount(7)
        self.res_tbl.setHorizontalHeaderLabels(["Phone", "Name", "Product", "Category", "City", "Image", "Details"])
        self.res_tbl.horizontalHeader().setStretchLastSection(True)
        self.res_tbl.setAlternatingRowColors(True)
        rl.addWidget(self.res_tbl, 1)

        # Export buttons row
        el = QHBoxLayout()
        for txt, slot, color in [("Export This Keyword (CSV)", self.export_results_csv, "#3498db"),
                                   ("Merge All + Dedup (PDF)", self.export_all_pdf, "#8e44ad"),
                                   ("Export All (CSV)", self.export_all, "#27ae60")]:
            b = QPushButton(txt)
            b.setStyleSheet(f"font-weight:bold; background:{color}; color:white; border:none; border-radius:4px; padding:7px 12px;")
            b.clicked.connect(slot)
            el.addWidget(b)
        rl.addLayout(el)

        rt.setLayout(rl)
        self.tabs.addTab(rt, "Results")

        ml.addWidget(self.tabs, 1)

        self.sb = QStatusBar()
        self.setStatusBar(self.sb)
        self.sb.showMessage("Ready")

    # --- Core ---
    def log(self, msg):
        self.log_txt.append(msg)
        c = self.log_txt.textCursor()
        c.movePosition(QTextCursor.End)
        self.log_txt.setTextCursor(c)
        self.sb.showMessage(msg)

    def add_keyword(self):
        raw = self.kw.text().strip()
        if not raw:
            return
        # Split by comma, semicolon, or newline and clean each keyword
        keywords = [k.strip().lower() for k in raw.replace(";", ",").split(",") if k.strip()]
        if not keywords:
            return
        db = get_db()
        added = 0
        for kw in keywords:
            # Skip duplicates already in queue
            exists = db.execute("SELECT 1 FROM tasks WHERE keyword=? AND status IN ('queued','running')", (kw,)).fetchone()
            if not exists:
                db.execute("INSERT INTO tasks(keyword,status) VALUES(?,?)", (kw, "queued"))
                added += 1
        db.commit()
        db.close()
        self.kw.clear()
        self.refresh_all()
        if added:
            self.log(f"Added {added} keyword(s): {', '.join(keywords)}")
        else:
            self.log("All keywords already queued or running")

    def _has_running_worker(self):
        """Check if there is currently a running worker."""
        if self._current_worker and self._current_worker.isRunning():
            return True
        return False

    def start_task(self, tid, kw):
        if self._has_running_worker():
            self.log(f"Task #{tid} queued (another task is running)")
            if tid not in self._pending_tasks:
                self._pending_tasks.append(tid)
            return

        if tid in self.workers and self.workers[tid].isRunning():
            return

        db = get_db()
        db.execute("UPDATE tasks SET status='running' WHERE id=?", (tid,))
        db.commit()
        db.close()
        w = ScraperWorker(tid, kw)
        w.signals.log.connect(self.log)
        w.signals.progress.connect(lambda t, c, n: self.on_progress(t, c, n))
        w.signals.finished.connect(self.on_finished)
        w.signals.error.connect(lambda m: (self.log(m), QMessageBox.critical(self, "Error", m)))
        self.workers[tid] = w
        self._current_worker = w
        w.start()
        self.refresh_queue()

    def start_all(self):
        db = get_db()
        rows = db.execute("SELECT id,keyword FROM tasks WHERE status='queued'").fetchall()
        db.close()
        if not rows:
            self.log("No queued tasks to start")
            return

        for r in rows:
            if r["id"] not in self._pending_tasks:
                self._pending_tasks.append(r["id"])

        if not self._has_running_worker():
            self._start_next_pending()

    def _start_next_pending(self):
        """Start the next pending task if any."""
        while self._pending_tasks:
            tid = self._pending_tasks.pop(0)
            db = get_db()
            row = db.execute("SELECT id,keyword FROM tasks WHERE id=? AND status='queued'", (tid,)).fetchone()
            db.close()
            if row:
                self.start_task(row["id"], row["keyword"])
                return

    def stop_all(self):
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.stop()
            self.log(f"Stopping task #{self._current_worker.task_id}...")
        self._pending_tasks.clear()
        self.log("All pending tasks cleared")

    def stop_task(self, tid):
        if tid in self.workers and self.workers[tid].isRunning():
            self.workers[tid].stop()
            self.log(f"Stopping task #{tid}...")
        if tid in self._pending_tasks:
            self._pending_tasks.remove(tid)

    def on_progress(self, tid, cur, tot):
        db = get_db()
        db.execute("UPDATE tasks SET processed_urls=? WHERE id=?", (cur, tid))
        db.commit()
        db.close()

    def on_finished(self, tid):
        self.workers.pop(tid, None)
        if self._current_worker and self._current_worker.task_id == tid:
            self._current_worker = None
        self.refresh_all()
        # Start next pending task
        if self._pending_tasks:
            self._start_next_pending()

    # --- Refresh ---
    def refresh_queue(self):
        db = get_db()
        rows = db.execute("SELECT * FROM tasks WHERE status IN ('queued','running','paused') ORDER BY id").fetchall()
        db.close()

        current_row_count = self.queue_tbl.rowCount()
        new_row_count = len(rows)
        if current_row_count != new_row_count:
            self.queue_tbl.setRowCount(new_row_count)
        else:
            # Just update existing rows to avoid flicker
            pass

        self.queue_tbl.setRowCount(new_row_count)
        for i, r in enumerate(rows):
            self.queue_tbl.setItem(i, 0, QTableWidgetItem(str(r["id"])))
            self.queue_tbl.setItem(i, 1, QTableWidgetItem(safe_text(r["keyword"])))

            status = r["status"]
            sw = QWidget()
            sl = QHBoxLayout(sw)
            sl.setContentsMargins(5, 2, 5, 2)
            lbl = QLabel({"queued": "QUEUED", "running": "RUNNING", "paused": "PAUSED"}.get(status, status))
            color = {"queued": "#f39c12", "running": "#27ae60", "paused": "#e74c3c"}.get(status, "#999")
            lbl.setStyleSheet(f"color:{color}; font-weight:bold;")
            sl.addWidget(lbl)
            self.queue_tbl.setCellWidget(i, 2, sw)

            pw = QWidget()
            pl = QHBoxLayout(pw)
            pl.setContentsMargins(5, 2, 5, 2)
            pb = QProgressBar()
            tot = r["total_urls"] or 0
            don = r["processed_urls"] or 0
            if tot > 0:
                pb.setMaximum(tot)
                pb.setValue(don)
                pb.setFormat(f"{don}/{tot}")
            else:
                pb.setMaximum(0)
            pb.setFixedWidth(200)
            pl.addWidget(pb)
            self.queue_tbl.setCellWidget(i, 3, pw)

            aw = QWidget()
            al = QHBoxLayout(aw)
            al.setContentsMargins(5, 2, 5, 2)
            if status == "queued":
                b = QPushButton("Start")
                b.setStyleSheet("background:#27ae60;color:white;border:none;border-radius:3px;padding:4px 10px;")
                b.clicked.connect(lambda _, tid=r["id"], kw=r["keyword"]: self.start_task(tid, kw))
                al.addWidget(b)
                d = QPushButton("X")
                d.setFixedWidth(26)
                d.setStyleSheet("background:#e74c3c;color:white;border:none;border-radius:3px;")
                d.clicked.connect(lambda _, tid=r["id"]: self._delete_task_by_id(tid))
                al.addWidget(d)
            elif status == "running":
                b = QPushButton("Stop")
                b.setStyleSheet("background:#e74c3c;color:white;border:none;border-radius:3px;padding:4px 10px;")
                b.clicked.connect(lambda _, tid=r["id"]: self.stop_task(tid))
                al.addWidget(b)
            self.queue_tbl.setCellWidget(i, 4, aw)
        self.queue_tbl.resizeColumnsToContents()

    def refresh_all(self):
        self.refresh_queue()
        self.load_history()
        self.load_results()

    def load_history(self):
        db = get_db()
        rows = db.execute("SELECT * FROM tasks WHERE status IN ('completed','paused','failed') ORDER BY id DESC").fetchall()
        db.close()
        self.hist_tbl.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.hist_tbl.setItem(i, 0, QTableWidgetItem(str(r["id"])))
            self.hist_tbl.setItem(i, 1, QTableWidgetItem(safe_text(r["keyword"])))
            self.hist_tbl.setItem(i, 2, QTableWidgetItem(safe_text(r["status"])))
            self.hist_tbl.setItem(i, 3, QTableWidgetItem(str(r["total_urls"] or 0)))
            self.hist_tbl.setItem(i, 4, QTableWidgetItem(str(r["processed_urls"] or 0)))
            self.hist_tbl.setItem(i, 5, QTableWidgetItem(safe_text(r["completed_at"])))
        self.hist_tbl.resizeColumnsToContents()

    def load_results(self):
        tid = self.task_combo.currentData()
        if tid is None:
            tid = -1
        flt = self.filter_inp.text().strip().lower()
        db = get_db()
        q = "SELECT * FROM results WHERE 1=1"
        p = []
        if tid and tid > 0:
            q += " AND task_id=?"
            p.append(tid)
        if flt:
            q += " AND (phone LIKE ? OR name LIKE ? OR product_needed LIKE ?)"
            p.extend([f"%{flt}%"] * 3)
        rows = db.execute(q + " ORDER BY id", p).fetchall()
        db.close()
        self.res_tbl.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.res_tbl.setItem(i, 0, QTableWidgetItem(safe_text(r["phone"])))
            self.res_tbl.setItem(i, 1, QTableWidgetItem(safe_text(r["name"])))
            self.res_tbl.setItem(i, 2, QTableWidgetItem(safe_text(r["product_needed"])))
            self.res_tbl.setItem(i, 3, QTableWidgetItem(safe_text(r["category"])))
            self.res_tbl.setItem(i, 4, QTableWidgetItem(safe_text(r["city"])))
            img_text = safe_text(r["image"])
            if len(img_text) > 40:
                img_text = img_text[:40] + "..."
            self.res_tbl.setItem(i, 5, QTableWidgetItem(img_text))
            self.res_tbl.setItem(i, 6, QTableWidgetItem(safe_text(r["other_details"], 100)))
        self.res_tbl.resizeColumnsToContents()
        self.sb.showMessage(f"{len(rows)} results")

        # Update combo only if task list changed
        db = get_db()
        tasks = db.execute("SELECT id,keyword FROM tasks ORDER BY id DESC").fetchall()
        db.close()
        current_data = self.task_combo.currentData()
        self.task_combo.blockSignals(True)
        self.task_combo.clear()
        self.task_combo.addItem("All Tasks", -1)
        for t in tasks:
            self.task_combo.addItem(f"#{t['id']} - {t['keyword']}", t["id"])
        # Restore selection
        if current_data is not None:
            for idx in range(self.task_combo.count()):
                if self.task_combo.itemData(idx) == current_data:
                    self.task_combo.setCurrentIndex(idx)
                    break
        self.task_combo.blockSignals(False)

    # --- Actions ---
    def hist_menu(self, pos):
        menu = QMenu(self)
        v = menu.addAction("View Results")
        d = menu.addAction("Delete")
        e = menu.addAction("Export CSV")
        act = menu.exec_(self.hist_tbl.mapToGlobal(pos))
        if act == v:
            self.view_results()
        elif act == d:
            self.delete_task()
        elif act == e:
            self.export_selected()

    def view_results(self):
        row = self.hist_tbl.currentRow()
        if row < 0:
            return
        i = self.hist_tbl.item(row, 0)
        if i:
            TaskDetailDialog(int(i.text()), self).exec_()

    def _get_selected_task_id(self):
        """Get task ID from history table selection, return None if invalid."""
        row = self.hist_tbl.currentRow()
        if row < 0:
            return None
        item = self.hist_tbl.item(row, 0)
        if not item:
            return None
        try:
            return int(item.text())
        except (ValueError, TypeError):
            return None

    def delete_task(self):
        tid = self._get_selected_task_id()
        if tid is None:
            return
        if QMessageBox.question(self, "Confirm", f"Delete task #{tid} and all its data?",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            db = get_db()
            delete_task_data(db, tid)
            db.close()
            self.refresh_all()

    def _delete_task_by_id(self, tid):
        """Delete a task by ID (used from queue table)."""
        if QMessageBox.question(self, "Confirm", f"Delete task #{tid}?",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            db = get_db()
            delete_task_data(db, tid)
            db.close()
            self.refresh_all()

    def export_selected(self):
        tid = self._get_selected_task_id()
        if tid is None:
            return
        db = get_db()
        rows = db.execute("SELECT * FROM results WHERE task_id=?", (tid,)).fetchall()
        db.close()
        default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"task_{tid}_export.csv")
        path, ok = QInputDialog.getText(self, "Export", "Path:", text=default_path)
        if not ok or not path:
            return
        count = export_rows_to_csv(rows, path)
        QMessageBox.information(self, "Done", f"Exported {count} rows")

    def export_all(self):
        default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "all_results.csv")
        path, ok = QInputDialog.getText(self, "Export All", "Path:", text=default_path)
        if not ok or not path:
            return
        db = get_db()
        rows = db.execute("SELECT * FROM results ORDER BY id").fetchall()
        db.close()
        count = export_rows_to_csv(rows, path)
        QMessageBox.information(self, "Done", f"Exported {count} rows")

    def export_results_csv(self):
        """Export currently filtered results (or selected keyword) to CSV."""
        tid = self.task_combo.currentData()
        if tid is None:
            tid = -1
        flt = self.filter_inp.text().strip().lower()
        db = get_db()
        q = "SELECT * FROM results WHERE 1=1"
        p = []
        if tid and tid > 0:
            q += " AND task_id=?"
            p.append(tid)
        if flt:
            q += " AND (phone LIKE ? OR name LIKE ? OR product_needed LIKE ?)"
            p.extend([f"%{flt}%"] * 3)
        rows = db.execute(q + " ORDER BY id", p).fetchall()
        db.close()

        if not rows:
            QMessageBox.information(self, "Empty", "No results to export")
            return

        # Get keyword name for default filename
        keyword = "all"
        if tid and tid > 0:
            db2 = get_db()
            r = db2.execute("SELECT keyword FROM tasks WHERE id=?", (tid,)).fetchone()
            db2.close()
            if r:
                keyword = r["keyword"].replace(" ", "_")
        default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{keyword}_results.csv")
        path, ok = QInputDialog.getText(self, "Export CSV", "Path:", text=default_path)
        if not ok or not path:
            return
        count = export_rows_to_csv(rows, path)
        QMessageBox.information(self, "Done", f"Exported {count} rows to CSV")

    def export_all_pdf(self):
        """Merge all results across all tasks into one PDF, removing duplicates."""
        db = get_db()
        rows = db.execute("SELECT * FROM results ORDER BY id").fetchall()
        db.close()

        if not rows:
            QMessageBox.information(self, "Empty", "No results to export")
            return

        unique_rows = deduplicate_rows(rows)
        default_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "all_results_merged.pdf")
        path, ok = QInputDialog.getText(self, "Merge All to PDF",
                                         f"Merged PDF: {len(rows)} total -> {len(unique_rows)} unique\nPath:",
                                         text=default_path)
        if not ok or not path:
            return
        count = export_rows_to_pdf(unique_rows, path, title="Chaicon Merged Results")
        QMessageBox.information(self, "Done",
                                f"PDF exported: {count} unique rows\n({len(rows) - count} duplicates removed)")

    def closeEvent(self, e):
        self.timer.stop()
        # Stop current worker
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.stop()
            self._current_worker.wait(5000)
        # Clear pending
        self._pending_tasks.clear()
        # Stop any remaining workers
        for w in self.workers.values():
            if w.isRunning():
                w.stop()
                w.wait(3000)
        e.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QMainWindow{background:#f5f6fa}
        QTableWidget{gridline-color:#dcdde1;font-size:13px}
        QHeaderView::section{background:#2c3e50;color:white;padding:6px;font-weight:bold}
        QTableWidget::item:selected{background:#3498db;color:white}
        QGroupBox{font-weight:bold;border:1px solid #bdc3c7;border-radius:6px;margin-top:10px;padding-top:15px}
        QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 5px}
    """)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())
