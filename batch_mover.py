"""
Batch Pending File Mover — v1.1
================================
Scans pending/ folder for .md files and moves them to
their assigned category folders based on the category
field inside each file.

What it does:
- Reads every .md file in pending/
- Extracts the category from the file metadata
- If category is valid → moves file to that category folder
- If category is missing/invalid → leaves in pending
- Updates ALL THREE databases with new file path and status
- Logs all moves and skips

No AI. No corrections. No content changes. Just move.
"""

import os
import sys
import time
import json
import base64
import re
import requests
import psycopg2
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict


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

BATCH_SIZE = 50
BATCH_DELAY = 3

# Category name → folder slug mapping
CATEGORY_SLUGS = {
    "Agriculture & Farming": "agriculture_farming",
    "Business & Finance": "business_finance",
    "Culture & Traditions": "culture_traditions",
    "Education & Learning": "education_learning",
    "Health & Medicine": "health_medicine",
    "Technology & Innovation": "technology_innovation",
    "Tourism & Travel": "tourism_travel",
    "History & Heritage": "history_heritage",
    "Food & Cuisine": "food_cuisine",
    "Music & Dance": "music_dance",
    "Language & Proverbs": "language_proverbs",
    "Religion & Spirituality": "religion_spirituality",
    "Sports & Games": "sports_games",
    "Fashion & Textiles": "fashion_textiles",
    "Environment & Nature": "environment_nature",
    "Governance & Leadership": "governance_leadership",
    "Family & Relationships": "family_relationships",
    "Arts & Crafts": "arts_crafts",
    "Science & Innovation": "science_innovation",
    "Other": "other",
}


# ===========================================================================
# GitHub Helpers
# ===========================================================================

def _github_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def list_pending_files() -> list:
    """Get all .md files from the pending/ folder."""
    all_files = []
    page = 1
    per_page = 100

    while True:
        url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/pending"
        params = {"page": page, "per_page": per_page}
        try:
            response = requests.get(url, headers=_github_headers(), params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if not data:
                    break
                for item in data:
                    if item["name"].endswith(".md"):
                        all_files.append(item)
                if len(data) < per_page:
                    break
                page += 1
            else:
                print(f"  List pending error: {response.status_code}")
                break
        except Exception as e:
            print(f"  List pending exception: {e}")
            break

    return all_files


def get_file_content(path: str) -> Optional[str]:
    """Get the decoded content of a file from GitHub."""
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    try:
        response = requests.get(url, headers=_github_headers(), timeout=15)
        if response.status_code == 200:
            content_b64 = response.json().get("content", "")
            if content_b64:
                return base64.b64decode(content_b64).decode("utf-8", errors="ignore")
        return None
    except Exception:
        return None


def get_file_sha(path: str) -> str:
    """Get the SHA of a file."""
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    try:
        response = requests.get(url, headers=_github_headers(), timeout=15)
        if response.status_code == 200:
            return response.json().get("sha", "")
        return ""
    except Exception:
        return ""


def move_file(source_path: str, dest_path: str, content: str) -> bool:
    """Move a file by creating at dest_path, then deleting source_path."""
    create_url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{dest_path}"
    create_payload = {
        "message": f"Batch move: {source_path} → {dest_path}",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }

    try:
        create_response = requests.put(create_url, json=create_payload, headers=_github_headers(), timeout=15)
        if create_response.status_code not in [200, 201]:
            print(f"    Failed to create {dest_path}: {create_response.status_code}")
            return False

        source_sha = get_file_sha(source_path)
        if source_sha:
            delete_url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{source_path}"
            delete_payload = {
                "message": f"Remove from pending after batch move: {source_path}",
                "sha": source_sha,
                "branch": "main",
            }
            delete_response = requests.delete(delete_url, json=delete_payload, headers=_github_headers(), timeout=15)
            if delete_response.status_code not in [200, 201]:
                print(f"    Warning: Created {dest_path} but failed to delete {source_path}")

        return True
    except Exception as e:
        print(f"    Move error: {e}")
        return False


# ===========================================================================
# Category Extraction
# ===========================================================================

def extract_category(file_content: str) -> Optional[str]:
    """Extract the category from a markdown file."""
    match = re.search(r'\*\*Category:\*\*\s*(.+?)(?:\n|$)', file_content)
    if match:
        category = match.group(1).strip()
        if category in CATEGORY_SLUGS:
            return category
        for valid_cat in CATEGORY_SLUGS:
            if valid_cat.lower() == category.lower():
                return valid_cat
    return None


def extract_submission_id(file_content: str) -> Optional[str]:
    """Extract submission ID from file content."""
    match = re.search(r'\*\*Submission ID:\*\*\s*(GHGPT-\d{4}-\d{4})', file_content)
    if match:
        return match.group(1)
    return None


# ===========================================================================
# Database Update — All Three Databases
# ===========================================================================

def update_database_status(submission_id: str, new_filename: str) -> bool:
    """Update the status and filename in all three databases."""
    updated = False
    now = datetime.now(timezone.utc).isoformat()

    # Supabase
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            from supabase import create_client
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            supabase.table("submissions").update({
                "status": "approved",
                "pending_filename": new_filename,
                "updated_at": now,
            }).eq("submission_id", submission_id).execute()
            updated = True
            print(f"    Supabase updated")
        except Exception as e:
            print(f"    Supabase update failed: {e}")

    # Neon
    if NEON_URL:
        try:
            conn = psycopg2.connect(NEON_URL, connect_timeout=10)
            cur = conn.cursor()
            cur.execute(
                "UPDATE submissions SET status = %s, pending_filename = %s, updated_at = %s WHERE submission_id = %s",
                ("approved", new_filename, now, submission_id)
            )
            conn.commit()
            cur.close()
            conn.close()
            updated = True
            print(f"    Neon updated")
        except Exception as e:
            print(f"    Neon update failed: {e}")

    # Fly.io PG
    if FLY_PG_URL:
        try:
            conn = psycopg2.connect(FLY_PG_URL, connect_timeout=10)
            cur = conn.cursor()
            cur.execute(
                "UPDATE submissions SET status = %s, pending_filename = %s, updated_at = %s WHERE submission_id = %s",
                ("approved", new_filename, now, submission_id)
            )
            conn.commit()
            cur.close()
            conn.close()
            updated = True
            print(f"    Fly.io PG updated")
        except Exception as e:
            print(f"    Fly.io PG update failed: {e}")

    if not updated:
        print(f"    WARNING: Could not update any database for {submission_id}")

    return updated


# ===========================================================================
# Stuck Files Report
# ===========================================================================

def find_stuck_files(pending_files: list) -> list:
    """Find files that have been in pending for over 48 hours."""
    stuck = []
    now = datetime.now(timezone.utc)

    for file_info in pending_files:
        # GitHub API doesn't give us creation time easily from the list endpoint
        # We check by reading the file content for the date
        content = get_file_content(file_info["path"])
        if content:
            date_match = re.search(r'\*\*Date:\*\*\s*(.+)', content)
            if date_match:
                try:
                    file_date_str = date_match.group(1).strip()
                    # Format: 2026-07-24 14:30:00 UTC
                    file_date = datetime.strptime(file_date_str, "%Y-%m-%d %H:%M:%S UTC")
                    file_date = file_date.replace(tzinfo=timezone.utc)
                    age_hours = (now - file_date).total_seconds() / 3600
                    if age_hours > 48:
                        stuck.append({
                            "path": file_info["path"],
                            "name": file_info["name"],
                            "hours": round(age_hours, 1),
                        })
                except Exception:
                    pass

    return stuck


# ===========================================================================
# Main
# ===========================================================================

def run_batch_mover():
    """Scan pending/, move files to category folders, update databases, log results."""
    print("=" * 60)
    print("Batch Pending File Mover v1.1")
    print("=" * 60)
    print(f"Repo: {KNOWLEDGE_REPO}")
    print(f"Batch size: {BATCH_SIZE}")
    print(f"GitHub token: {'SET' if GITHUB_TOKEN else 'NOT SET'}")
    print(f"Supabase: {'SET' if SUPABASE_URL else 'NOT SET'}")
    print(f"Neon: {'SET' if NEON_URL else 'NOT SET'}")
    print(f"Fly.io PG: {'SET' if FLY_PG_URL else 'NOT SET'}")
    print("-" * 60)
    sys.stdout.flush()

    if not GITHUB_TOKEN or not KNOWLEDGE_REPO:
        print("ERROR: GH_TOKEN and KNOWLEDGE_REPO must be set.")
        return

    # Get all pending files
    print("Scanning pending/ folder...")
    pending_files = list_pending_files()
    total_files = len(pending_files)
    print(f"Found {total_files} files in pending/")
    sys.stdout.flush()

    if total_files == 0:
        print("Nothing to do.")
        return

    moved = 0
    skipped = 0
    errors = 0
    db_updated = 0
    log_entries = []

    # Process in batches
    for batch_start in range(0, total_files, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, total_files)
        batch = pending_files[batch_start:batch_end]

        print(f"\nBatch {batch_start // BATCH_SIZE + 1}: Processing files {batch_start + 1}-{batch_end}...")
        sys.stdout.flush()

        for file_info in batch:
            file_path = file_info["path"]
            file_name = file_info["name"]

            print(f"  {file_name}...", end=" ")
            sys.stdout.flush()

            # Read file content
            content = get_file_content(file_path)
            if not content:
                print("SKIPPED (could not read file)")
                skipped += 1
                log_entries.append(f"SKIP | {file_name} | Could not read file")
                continue

            # Check if file is empty or corrupted
            if len(content.strip()) < 50:
                print("SKIPPED (file too short or empty)")
                skipped += 1
                log_entries.append(f"SKIP | {file_name} | Empty or too short")
                continue

            # Extract category
            category = extract_category(content)
            if not category:
                print("SKIPPED (no valid category found)")
                skipped += 1
                log_entries.append(f"SKIP | {file_name} | No valid category")
                continue

            # Extract submission ID
            submission_id = extract_submission_id(content)

            # Get destination folder
            folder = CATEGORY_SLUGS.get(category, "other")
            dest_path = f"{folder}/{file_name}"

            # Check if destination already exists
            existing_sha = get_file_sha(dest_path)
            if existing_sha:
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                base_name = file_name.replace(".md", "")
                dest_path = f"{folder}/{timestamp}-{base_name}.md"

            # Move the file on GitHub
            success = move_file(file_path, dest_path, content)
            if success:
                sid = submission_id or "unknown"
                print(f"MOVED → {dest_path}", end=" ")
                moved += 1

                # Update databases
                if submission_id:
                    db_ok = update_database_status(submission_id, dest_path)
                    if db_ok:
                        db_updated += 1
                        print("+ DB updated")
                    else:
                        print("(DB update failed)")
                else:
                    print("(no submission ID)")

                log_entries.append(f"MOVE | {file_name} → {dest_path} | {sid} | {category}")
            else:
                print("ERROR (move failed)")
                errors += 1
                log_entries.append(f"ERROR | {file_name} | Move failed")

        # Delay between batches
        if batch_end < total_files:
            print(f"  Waiting {BATCH_DELAY}s before next batch...")
            sys.stdout.flush()
            time.sleep(BATCH_DELAY)

    # Stuck files report
    print("\nChecking for stuck files...")
    stuck_files = find_stuck_files(pending_files)
    if stuck_files:
        print(f"  ⚠️  {len(stuck_files)} files stuck in pending for over 48 hours:")
        for sf in stuck_files[:10]:
            print(f"    - {sf['name']} ({sf['hours']} hours)")
        if len(stuck_files) > 10:
            print(f"    ... and {len(stuck_files) - 10} more")
    else:
        print("  No stuck files found.")

    # Print summary
    print("\n" + "=" * 60)
    print(f"SUMMARY: {moved} moved | {db_updated} DB updated | {skipped} skipped | {errors} errors | {total_files} total")
    if stuck_files:
        print(f"STUCK: {len(stuck_files)} files in pending > 48 hours")
    print("=" * 60)

    # Save log
    log_content = f"# Batch Move Log — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
    log_content += f"# {moved} moved | {db_updated} DB updated | {skipped} skipped | {errors} errors\n"
    if stuck_files:
        log_content += f"# {len(stuck_files)} files stuck > 48 hours\n"
    log_content += "\n"
    log_content += "\n".join(log_entries)

    log_path = f"admin/batch-move-log-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.md"
    log_url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{log_path}"
    log_payload = {
        "message": f"Batch move log: {moved} moved, {skipped} skipped",
        "content": base64.b64encode(log_content.encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }

    try:
        requests.put(log_url, json=log_payload, headers=_github_headers(), timeout=15)
        print(f"Log saved to {log_path}")
    except Exception as e:
        print(f"Failed to save log: {e}")


if __name__ == "__main__":
    run_batch_mover()
