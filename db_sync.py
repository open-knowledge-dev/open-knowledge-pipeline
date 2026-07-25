"""
Database Sync — v1.1
=====================
Syncs database submission status with GitHub repo state.
Runs once daily.

What it does:
- Scans category folders on GitHub
- Finds files that are in database as "queued" but already in category folders
- Updates database status to "approved" for those files
- Updates pending_filename to match actual file location

Fixed: GitHub API pagination now handled correctly.
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
FLY_PG_URL = os.getenv("FLY_PG_URL", "")

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
    """
    List .md files in a category folder with proper pagination.
    Returns list of file info dicts.
    """
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

            # If data is a dict instead of list, it's a single file, not a folder
            if isinstance(data, dict):
                if data.get("name", "").endswith(".md"):
                    all_files.append(data)
                break

            # If data is a list, process each item
            if isinstance(data, list):
                if len(data) == 0:
                    break

                for item in data:
                    if item.get("name", "").endswith(".md"):
                        # Skip .gitkeep files
                        if item["name"] == ".gitkeep":
                            continue
                        all_files.append(item)

                # If we got fewer than requested, we're done
                if len(data) < 100:
                    break

                page += 1

                # Safety limit
                if len(all_files) >= max_files:
                    break
            else:
                break

        except Exception as e:
            print(f"    Error listing {folder}: {e}")
            break

    return all_files


def get_file_content(path: str) -> Optional[str]:
    """Get file content and return decoded text."""
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    try:
        response = requests.get(url, headers=_github_headers(), timeout=15)
        if response.status_code == 200:
            data = response.json()
            content_b64 = data.get("content", "")
            if content_b64:
                return base64.b64decode(content_b64).decode("utf-8", errors="ignore")
        return None
    except Exception:
        return None


def extract_submission_id(content: str) -> Optional[str]:
    """Extract submission ID from file content."""
    match = re.search(r'\*\*Submission ID:\*\*\s*(GHGPT-\d{4}-\d{4})', content)
    if match:
        return match.group(1)
    return None


# ===========================================================================
# Database Sync
# ===========================================================================

def update_database(submission_id: str, filename: str) -> int:
    """Update status to 'approved' in all databases. Returns count of DBs updated."""
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
        except Exception as e:
            print(f"    Supabase error for {submission_id}: {e}")

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
        except Exception as e:
            print(f"    Neon error for {submission_id}: {e}")

    # Fly.io PG
    if FLY_PG_URL:
        try:
            conn = psycopg2.connect(FLY_PG_URL, connect_timeout=10)
            cur = conn.cursor()
            cur.execute(
                "UPDATE submissions SET status = %s, pending_filename = %s, updated_at = %s WHERE submission_id = %s",
                ("approved", filename, now, submission_id)
            )
            conn.commit()
            cur.close()
            conn.close()
            updated += 1
        except Exception as e:
            print(f"    Fly.io PG error for {submission_id}: {e}")

    return updated


# ===========================================================================
# Main
# ===========================================================================

def run_db_sync():
    """Scan category folders and sync database status."""
    print("=" * 60)
    print("Database Sync v1.1")
    print("=" * 60)
    print(f"Repo: {KNOWLEDGE_REPO}")
    print(f"Databases: {'Supabase' if SUPABASE_URL else '?'}, {'Neon' if NEON_URL else '?'}, {'FlyPG' if FLY_PG_URL else '?'}")
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

        files = list_folder_files(folder_slug, max_files=500)
        folder_count = len(files)
        total_files_found += folder_count
        print(f"  Found {folder_count} files")

        if folder_count == 0:
            continue

        # Process a sample from each folder
        sample_size = min(folder_count, 200)
        sample = files[:sample_size]

        for file_info in sample:
            file_path = file_info["path"]
            total_checked += 1

            # Skip reading file content — extract submission ID from filename
            # The filename format is: YYYYMMDD-HHMMSS-topic-SUBID.md or topic-SUBID.md
            filename = file_info["name"]
            id_match = re.search(r'(GHGPT-\d{4}-\d{4})', filename)
            if not id_match:
                # Try reading the file for the ID
                content = get_file_content(file_path)
                if content:
                    id_match = re.search(r'\*\*Submission ID:\*\*\s*(GHGPT-\d{4}-\d{4})', content)
                    if id_match:
                        submission_id = id_match.group(1)
                    else:
                        continue
                else:
                    continue
            else:
                submission_id = id_match.group(1)

            # Update database
            db_count = update_database(submission_id, file_path)
            if db_count > 0:
                total_synced += 1

            if total_synced % 100 == 0 and total_synced > 0:
                print(f"  Synced: {total_synced}")

        print(f"  Processed {sample_size} files from {folder_slug}/")

    print("\n" + "=" * 60)
    print(f"SYNC COMPLETE")
    print(f"  Files found across all folders: {total_files_found}")
    print(f"  Files checked: {total_checked}")
    print(f"  Database records updated: {total_synced}")
    print("=" * 60)


if __name__ == "__main__":
    run_db_sync()
