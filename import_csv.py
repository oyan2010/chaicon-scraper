import csv
import os
import sqlite3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "chaicon_tasks.db")
CSV_PATH = os.path.join(SCRIPT_DIR, "manufacturers.csv")

SCHEMA = """
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
        other_details TEXT,
        scraped_at TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY(task_id) REFERENCES tasks(id)
    );
"""


def main():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print("Removed old DB")

    if not os.path.exists(CSV_PATH):
        print("No CSV to import")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if rows:
        conn.execute(
            "INSERT INTO tasks(keyword,status,completed_at,total_urls,processed_urls) VALUES(?,?,datetime('now','localtime'),?,?)",
            ("legacy_data", "completed", len(rows), len(rows)),
        )
        task_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for r in rows:
            conn.execute(
                "INSERT INTO results(task_id,url,phone,name,product_needed,category,city,image,other_details) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    "",
                    r.get("Phone Number", ""),
                    r.get("Name", ""),
                    r.get("Product Needed", ""),
                    r.get("Category", ""),
                    "",
                    r.get("Image", ""),
                    r.get("Other Details", ""),
                ),
            )
        conn.commit()
        print(f"Imported {len(rows)} rows as task #{task_id}")
    else:
        print("CSV is empty")

    conn.close()
    print("Done")


if __name__ == "__main__":
    main()
