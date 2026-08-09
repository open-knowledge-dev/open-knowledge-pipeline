"""
One-time setup — creates all required tables on Render PostgreSQL.
Run once via GitHub Actions, then delete this file.
"""

import os
import sys
import psycopg2

RENDER_DB_URL = os.getenv("RENDER_DB_URL", "")

if not RENDER_DB_URL:
    print("ERROR: RENDER_DB_URL not set")
    sys.exit(1)

conn = psycopg2.connect(RENDER_DB_URL)
cur = conn.cursor()

statements = [
    """
    CREATE TABLE IF NOT EXISTS submissions (
        submission_id TEXT PRIMARY KEY,
        topic TEXT,
        category TEXT,
        knowledge TEXT,
        region TEXT,
        language TEXT DEFAULT 'English',
        email TEXT DEFAULT '',
        status TEXT DEFAULT 'queued',
        ip_hash TEXT DEFAULT '',
        content_hash TEXT DEFAULT '',
        pending_filename TEXT DEFAULT '',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS submission_queue (
        id SERIAL PRIMARY KEY,
        submission_id TEXT NOT NULL,
        payload JSONB,
        status TEXT DEFAULT 'queued',
        retry_count INTEGER DEFAULT 0,
        max_retries INTEGER DEFAULT 3,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rate_limits (
        id SERIAL PRIMARY KEY,
        ip_hash TEXT NOT NULL,
        window_start TIMESTAMPTZ DEFAULT NOW(),
        created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS error_logs (
        id SERIAL PRIMARY KEY,
        error_type TEXT,
        message TEXT,
        submission_id TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
]

for stmt in statements:
    try:
        cur.execute(stmt)
        conn.commit()
        print("OK")
    except Exception as e:
        conn.rollback()
        print(f"FAILED: {e}")

cur.close()
conn.close()
print("Done.")
