"""
Weekly database maintenance script for Ghana-GPT.
==================================================
Purges old records from Supabase, Neon, and Render to stay within free tier limits.
Runs via GitHub Actions every Sunday at midnight UTC.

Purges:
  - submission_queue: records older than 7 days (sent/dead)
  - rate_limits: records older than 14 days
  - error_logs: records older than 30 days

Does NOT touch the submissions table.
All queries use parameterized statements to prevent SQL injection.
"""

import os
import sys
import psycopg2
from datetime import datetime, timezone, timedelta


def get_connection(connection_string: str):
    """Create a database connection with a short timeout."""
    if not connection_string:
        return None
    try:
        return psycopg2.connect(connection_string, connect_timeout=10)
    except Exception as e:
        print(f"  Failed to connect: {e}")
        return None


def purge_database(connection_string: str, label: str) -> dict:
    """
    Purge old records from a single database.
    Returns a dict with counts of deleted rows per table.
    """
    results = {"queue": 0, "rate_limits": 0, "error_logs": 0}

    conn = get_connection(connection_string)
    if not conn:
        print(f"  {label}: Connection failed — skipping")
        return results

    try:
        cur = conn.cursor()

        cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        cur.execute(
            "DELETE FROM submission_queue WHERE status IN ('sent', 'dead') AND updated_at < %s",
            (cutoff_7d,)
        )
        results["queue"] = cur.rowcount

        cutoff_14d = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        cur.execute(
            "DELETE FROM rate_limits WHERE created_at < %s",
            (cutoff_14d,)
        )
        results["rate_limits"] = cur.rowcount

        cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        cur.execute(
            "DELETE FROM error_logs WHERE created_at < %s",
            (cutoff_30d,)
        )
        results["error_logs"] = cur.rowcount

        conn.commit()
        cur.close()
        print(f"  {label}: Queue={results['queue']}, RateLimits={results['rate_limits']}, ErrorLogs={results['error_logs']}")

    except Exception as e:
        print(f"  {label}: Error during purge: {e}")
        conn.rollback()
    finally:
        conn.close()

    return results


def main():
    """Run purge on Supabase, Neon, and Render."""
    print(f"=== Ghana-GPT Database Cleanup ===")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print()

    supabase_db_url = os.getenv("SUPABASE_DB_URL", "")
    neon_url = os.getenv("NEON_URL", "")
    render_db_url = os.getenv("RENDER_DB_URL", "")

    if not supabase_db_url and not neon_url and not render_db_url:
        print("ERROR: No database URLs configured.")
        sys.exit(1)

    if supabase_db_url:
        print("Purging Supabase...")
        purge_database(supabase_db_url, "Supabase")
        print()

    if neon_url:
        print("Purging Neon...")
        purge_database(neon_url, "Neon")
        print()

    if render_db_url:
        print("Purging Render...")
        purge_database(render_db_url, "Render")
        print()

    print(f"=== Cleanup Complete ===")
    print(f"Finished: {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    main()
