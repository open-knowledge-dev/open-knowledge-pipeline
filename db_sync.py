"""
Database Sync — v1.4
=====================
Syncs database submission status with GitHub repo state.
Runs once daily. Updates Supabase and Neon automatically.
Uses batch updates for speed — processes all files in one run.

What it does:
- Scans category folders on GitHub
- Collects all submission IDs from filenames
- Batch updates Supabase and Neon in one call per folder
"""

import os
import sys
import json
import base64
import re
import requests
import psycopg2
from datetime import datetime, timezone
from typing import Optional, Dict, List


# ===========================================================================
# Configuration
# ===========================================================================

GITHUB_TOKEN = os.getenv("GH_TOKEN", "")
KNOWLEDGE_REPO = os.getenv("KNOWLEDGE_REPO", "")
GITHUB_API = "https://api.github.com"

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
NEON_URL = os.getenv("NEON_URL", "")

CATEGORY_SLUGS = {
    "agriculture_farming": "Agriculture & Farming",
    "business_finance": "Business & Finance",
    "culture_traditions": "Culture & Traditions",
    "education_learning": "Education & Learning",
    "health_medicine": "Health & Medicine",
    "technology_innovation": "Technology & Innovation",
    "tourism_travel": "Tourism & Travel",
    "history_heritage": "History & Heritage",
    "food_cuisine": "Food & Cuisine",
    "music_dance": "Music & Dance",
    "language_proverbs": "Language & Proverbs",
    "religion_spirituality": "Religion & Spirituality",
    "sports_games": "Sports & Games",
    "fashion_textiles": "Fashion & Textiles",
    "environment_nature": "Environment & Nature",
    "governance_leadership": "Governance & Leadership",
    "family_relationships": "Family & Relationships",
    "arts_crafts": "Arts & Crafts",
    "science_innovation": "Science & Innovation",
    "other": "Other",
}


# ===========================================================================
# GitHub Helpers
# ===========================================================================

def _github_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def list_folder_files(folder: str) -> List[Dict]:
    """List .md files in a category folder with pagination."""
    all_files = []
    page = 1

    while True:
        url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{folder}"
        params = {"page": page, "per_page": 100}

        try:
            response = requests.get(url, headers=_github_headers(), params=params, timeout=15)
            if response.status_code != 200:
                break

            data = response.json()

            if isinstance(data, dict):
                if data.get("name", "").endswith(".md"):
                    all_files.append(data)
                break

            if isinstance(data, list):
                if len(data) == 0:
                    break
                for item in data:
                    if item.get("name", "").endswith(".md") and item["name"] != ".gitkeep":
                        all_files.append(item)
                if len(data) < 100:
                    break
                page += 1
            else:
                break
        except Exception as e:
            print(f"    Error listing {folder}: {e}")
            break

    return all_files


def extract_submission_id_from_filename(filename: str) -> Optional[str]:
    """Extract submission ID from filename."""
    match = re.search(r'GHGPT-(\d{4})-(\d{4})', filename)
    if match:
        return f"GHGPT-{match.group(1)}-{match.group(2)}"

    match = re.search(r'-(\d{4})\.md$', filename)
    if match:
        seq = match.group(1)
        date_match = re.search(r'^(\d{4})\d{4}-\d{6}-', filename)
        if date_match:
            year = date_match.group(1)
            return f"GHGPT-{year}-{seq}"
        return f"GHGPT-2026-{seq}"

    return None


# ===========================================================================
# Batch Database Sync
# ===========================================================================

def batch_update_supabase(submission_ids: List[str], folder_name: str) -> int:
    """Batch update Supabase. Returns count of updated rows."""
    if not SUPABASE_URL or not SUPABASE_KEY or not submission_ids:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    updated = 0

    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

        # Process in batches of 50
        for i in range(0, len(submission_ids), 50):
            batch = submission_ids[i:i+50]
            for sid in batch:
                try:
                    supabase.table("submissions").update({
                        "status": "approved",
                        "pending_filename": f"{folder_name}/{sid}.md",
                        "updated_at": now,
                    }).eq("submission_id", sid).execute()
                    updated += 1
                except Exception:
                    pass
    except Exception:
        pass

    return updated


def batch_update_neon(submission_ids: List[str], folder_name: str) -> int:
    """Batch update Neon. Returns count of updated rows."""
    if not NEON_URL or not submission_ids:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    updated = 0

    try:
        conn = psycopg2.connect(NEON_URL, connect_timeout=10)
        cur = conn.cursor()

        for sid in submission_ids:
            try:
                cur.execute(
                    "UPDATE submissions SET status = %s, pending_filename = %s, updated_at = %s WHERE submission_id = %s",
                    ("approved", f"{folder_name}/{sid}.md", now, sid)
                )
                updated += 1
            except Exception:
                conn.rollback()

        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass

    return updated


# ===========================================================================
# Main
# ===========================================================================

def run_db_sync():
    """Scan all category folders and batch sync databases."""
    print("=" * 60)
    print("Database Sync v1.4 — Batch Mode")
    print("=" * 60)
    print(f"Repo: {KNOWLEDGE_REPO}")
    print(f"Databases: Supabase + Neon")
    sys.stdout.flush()

    if not GITHUB_TOKEN or not KNOWLEDGE_REPO:
        print("ERROR: GH_TOKEN and KNOWLEDGE_REPO must be set.")
        return

    total_supabase = 0
    total_neon = 0
    total_files = 0
    total_ids = 0

    for folder_slug, category_name in CATEGORY_SLUGS.items():
        print(f"\n{folder_slug}/...", end=" ")
        sys.stdout.flush()

        files = list_folder_files(folder_slug)
        folder_count = len(files)
        total_files += folder_count

        if folder_count == 0:
            print("0 files")
            continue

        # Extract all submission IDs from this folder
        submission_ids = []
        for file_info in files:
            sid = extract_submission_id_from_filename(file_info["name"])
            if sid:
                submission_ids.append(sid)

        total_ids += len(submission_ids)
        print(f"{folder_count} files, {len(submission_ids)} IDs", end=" ")

        if not submission_ids:
            print("")
            continue

        # Batch update both databases
        sup_count = batch_update_supabase(submission_ids, folder_slug)
        neon_count = batch_update_neon(submission_ids, folder_slug)
        total_supabase += sup_count
        total_neon += neon_count
        print(f"→ Supabase:{sup_count} Neon:{neon_count}")

    print("\n" + "=" * 60)
    print(f"SYNC COMPLETE")
    print(f"  Files scanned: {total_files}")
    print(f"  IDs extracted: {total_ids}")
    print(f"  Supabase updated: {total_supabase}")
    print(f"  Neon updated: {total_neon}")
    print(f"  Fly.io PG: update manually via 'fly postgres connect'")
    print("=" * 60)


if __name__ == "__main__":
    run_db_sync()
