import sqlite3
import os
from contextlib import contextmanager

DB_FILE = os.environ.get("FLOW_CACHE_DB", "flow_cache.db")

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Accounts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                email TEXT PRIMARY KEY,
                credits INTEGER,
                daily_free_credits_remaining INTEGER,
                daily_cycle_date TEXT,
                worker_id TEXT,
                updated_at TEXT
            )
        """)
        
        # Projects table (global)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                name TEXT PRIMARY KEY,
                last_accessed TEXT
            )
        """)
        
        # Project workers table (worker specific)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS project_workers (
                project_name TEXT,
                worker_id TEXT,
                url TEXT,
                local_uuid TEXT,
                characters TEXT,
                last_characters_updated TEXT,
                images TEXT,
                last_images_updated TEXT,
                videos TEXT,
                last_videos_updated TEXT,
                PRIMARY KEY (project_name, worker_id),
                FOREIGN KEY (project_name) REFERENCES projects(name) ON DELETE CASCADE
            )
        """)
        
        conn.commit()

@contextmanager
def get_connection():
    # Enable WAL mode for better concurrency
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    # Return rows as dict-like objects
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
    finally:
        conn.close()

# Initialize DB on module import
init_db()
