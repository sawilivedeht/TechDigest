import sqlite3, hashlib

import logging
logger = logging.getLogger("techdigest.storage.dedup")

class SeenStore:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS seen "
            "(hash TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        self.conn.commit()

    def is_new(self, url: str) -> bool:
        h = hashlib.sha256(url.encode()).hexdigest()
        row = self.conn.execute("SELECT 1 FROM seen WHERE hash = ?", (h,)).fetchone()
        return row is None

    def mark_seen(self, url: str) -> None:
        h = hashlib.sha256(url.encode()).hexdigest()
        self.conn.execute("INSERT OR IGNORE INTO seen (hash) VALUES (?)", (h,))
        self.conn.commit()