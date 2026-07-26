"""
Database Sync — v1.2
=====================
Syncs database submission status with GitHub repo state.
Runs once daily. Updates Supabase and Neon automatically.
Fly.io PG updated manually via fly postgres connect (internal network).

What it does:
- Scans category folders on GitHub
- Finds files already in category folders
- Updates Supabase and Neon status to "approved"
- Updates pending_filename to match actual file location
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


def list_folder_files(folder: str, max_files: int = 500) -> List[Dict]:
    """List .md files in a category folder with proper pagination."""
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
                if len(all_files) >= max_files:
                    break
            else:
                break
        except Exception as e:
            print(f"    Error listing {folder}: {e}")
            break

    return all_files


def extract_submission_id_from_filename(filename: str) -> Optional[str]:
    """Extract submission ID from filename."""
    match = re.search(r'(GHGPT-\d{4}-\d{4})', filename)
    if match:
        return match.group(1)
    return None


# ===========================================================================
# Database Sync
# ===========================================================================

def update_databases(submission_id: str, filename: str) -> int:
    """Update status to 'approved' in Supabase and Neon. Returns count of DBs updated."""
    updated = 0
    now = datetime.now(timezone.utc).isoformat()

    # Supabase
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            from supabase import create_client
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            supabase.table("submissions").update({
                "status": "approved",
                "pending_filename": filename,
                "updated_at": now,
            }).eq("submission_id", submission_id).execute()
            updated += 1
        except Exception:
            pass

    # Neon
    if NEON_URL:
        try:
            conn = psycopg2.connect(NEON_URL, connect_timeout=10)
            cur = conn.cursor()
            cur.execute(
                "UPDATE submissions SET status = %s, pending_filename = %s, updated_at = %s WHERE submission_id = %s",
                ("approved", filename, now, submission_id)
            )
            conn.commit()
            cur.close()
            conn.close()
            updated += 1
        except Exception:
            pass

    return updated


# ===========================================================================
# Main
# ===========================================================================

def run_db_sync():
    """Scan category folders and sync Supabase + Neon databases."""
    print("=" * 60)
    print("Database Sync v1.2")
    print("=" * 60)
    print(f"Repo: {KNOWLEDGE_REPO}")
    print(f"Databases: Supabase + Neon (Fly.io PG synced manually)")
    sys.stdout.flush()

    if not GITHUB_TOKEN or not KNOWLEDGE_REPO:
        print("ERROR: GH_TOKEN and KNOWLEDGE_REPO must be set.")
        return

    total_synced = 0
    total_checked = 0
    total_files_found = 0

    for folder_slug, category_name in CATEGORY_SLUGS.items():
        print(f"\nScanning {folder_slug}/...")
        sys.stdout.flush()

        files = list_folder_files(folder_slug, max_files=300)
        folder_count = len(files)
        total_files_found += folder_count
        print(f"  Found {folder_count} files")

        if folder_count == 0:
            continue

        for file_info in files:
            file_path = file_info["path"]
            filename = file_info["name"]
            total_checked += 1

            # Extract submission ID from filename
            submission_id = extract_submission_id_from_filename(filename)
            if not submission_id:
                continue

            # Update Supabase + Neon
            db_count = update_databases(submission_id, file_path)
            if db_count > 0:
                total_synced += 1

            if total_synced % 100 == 0 and total_synced > 0:
                print(f"  Synced: {total_synced}")

    print("\n" + "=" * 60)
    print(f"SYNC COMPLETE")
    print(f"  Files found across all folders: {total_files_found}")
    print(f"  Files checked: {total_checked}")
    print(f"  Database records updated: {total_synced}")
    print(f"  Fly.io PG: update manually via 'fly postgres connect'")
    print("=" * 60)


if __name__ == "__main__":
    run_db_sync()
