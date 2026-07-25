"""
Batch Pending File Mover — v2.0
================================
High-speed file mover for pending/ folder.
Designed for 5,000+ files/day throughput.

What it does:
- Reads .md files from pending/ in bulk
- Extracts category from each file
- Moves valid files to category folders via GitHub API
- Leaves invalid/corrupt files in pending
- Processes 500 files per run, ~15 minutes
- Runs every 2 hours (12x/day = 6,000 files/day capacity)
- State file tracking — resumes if interrupted

No database updates. No content changes. Just move files.
Database sync handled separately by db_sync.py.
"""

import os
import sys
import time
import json
import base64
import re
import requests
from datetime import datetime, timezone
from typing import Optional, Tuple, List, Dict


# ===========================================================================
# Configuration
# ===========================================================================

GITHUB_TOKEN = os.getenv("GH_TOKEN", "")
KNOWLEDGE_REPO = os.getenv("KNOWLEDGE_REPO", "")
GITHUB_API = "https://api.github.com"
MAX_FILES_PER_RUN = 500
BATCH_SIZE = 100
BATCH_DELAY = 1

STATE_FILE_PATH = "admin/batch-mover-state.json"

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


def _github_api_get(url: str, params: dict = None) -> Tuple[int, any]:
    """Make a GitHub API GET request. Returns (status_code, data)."""
    try:
        response = requests.get(url, headers=_github_headers(), params=params, timeout=15)
        if response.status_code == 200:
            return 200, response.json()
        return response.status_code, None
    except Exception as e:
        return 0, str(e)


def _github_api_put(url: str, payload: dict) -> int:
    """Make a GitHub API PUT request. Returns status_code."""
    try:
        response = requests.put(url, json=payload, headers=_github_headers(), timeout=15)
        return response.status_code
    except Exception:
        return 0


def _github_api_delete(url: str, payload: dict) -> int:
    """Make a GitHub API DELETE request. Returns status_code."""
    try:
        response = requests.delete(url, json=payload, headers=_github_headers(), timeout=15)
        return response.status_code
    except Exception:
        return 0


def list_pending_files(page: int = 1) -> Tuple[List[Dict], int]:
    """
    Get .md files from pending/ folder.
    Returns (files_list, next_page).
    """
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/pending"
    params = {"page": page, "per_page": 100}
    status, data = _github_api_get(url, params)

    if status != 200 or not data:
        return [], 0

    files = [item for item in data if item.get("name", "").endswith(".md")]

    if isinstance(data, list) and len(data) == 100:
        return files, page + 1
    return files, 0


def get_file_content(path: str) -> Optional[str]:
    """Get decoded content of a file from GitHub."""
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    status, data = _github_api_get(url)
    if status == 200 and data:
        content_b64 = data.get("content", "")
        if content_b64:
            return base64.b64decode(content_b64).decode("utf-8", errors="ignore")
    return None


def get_file_sha(path: str) -> str:
    """Get the SHA of a file."""
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    status, data = _github_api_get(url)
    if status == 200 and data:
        return data.get("sha", "")
    return ""


def create_github_file(path: str, content: str, message: str) -> bool:
    """Create a file on GitHub. Returns True on success."""
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }
    status = _github_api_put(url, payload)
    return status in [200, 201]


def delete_github_file(path: str, sha: str, message: str) -> bool:
    """Delete a file from GitHub. Returns True on success."""
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    payload = {"message": message, "sha": sha, "branch": "main"}
    status = _github_api_delete(url, payload)
    return status in [200, 201]


def move_file(source_path: str, dest_path: str, content: str) -> bool:
    """Move a file: create at dest, delete source. Returns True on success."""
    # Create destination file
    if not create_github_file(dest_path, content, f"Move: {source_path} → {dest_path}"):
        return False

    # Delete source file
    source_sha = get_file_sha(source_path)
    if source_sha:
        delete_github_file(source_path, source_sha, f"Remove from pending: {source_path}")

    return True


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
# State File
# ===========================================================================

def load_state() -> Dict:
    """Load mover state from the knowledge repo."""
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{STATE_FILE_PATH}"
    status, data = _github_api_get(url)
    if status == 200 and data:
        content_b64 = data.get("content", "")
        if content_b64:
            try:
                return json.loads(base64.b64decode(content_b64).decode("utf-8"))
            except Exception:
                pass
    return {"last_page": 1, "last_index": 0, "total_moved": 0, "last_run": ""}


def save_state(state: Dict) -> bool:
    """Save mover state to the knowledge repo."""
    content_json = json.dumps(state, indent=2, default=str)
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{STATE_FILE_PATH}"
    sha = get_file_sha(STATE_FILE_PATH)

    payload = {
        "message": f"Update mover state: {state.get('total_moved', 0)} moved",
        "content": base64.b64encode(content_json.encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    status = _github_api_put(url, payload)
    return status in [200, 201]


# ===========================================================================
# Main
# ===========================================================================

def run_batch_mover():
    """Move files from pending/ to category folders. Fast. No DB updates."""
    print("=" * 60)
    print("Batch Pending File Mover v2.0")
    print("=" * 60)
    print(f"Repo: {KNOWLEDGE_REPO}")
    print(f"Max files per run: {MAX_FILES_PER_RUN}")
    print(f"Runs: Every 2 hours | Capacity: 6,000 files/day")
    print("-" * 60)
    sys.stdout.flush()

    if not GITHUB_TOKEN or not KNOWLEDGE_REPO:
        print("ERROR: GH_TOKEN and KNOWLEDGE_REPO must be set.")
        return

    # Load state
    state = load_state()
    start_page = state.get("last_page", 1)
    start_index = state.get("last_index", 0)
    total_moved_total = state.get("total_moved", 0)

    print(f"Resuming from page {start_page}, index {start_index}")
    print(f"Total moved so far: {total_moved_total}")
    sys.stdout.flush()

    moved = 0
    skipped = 0
    errors = 0
    current_page = start_page
    current_index = start_index
    log_entries = []
    all_files = []

    # Collect files from pending/ starting from last page
    print("Scanning pending/ folder...")
    page = current_page
    while True:
        files, next_page = list_pending_files(page)
        if not files:
            break
        all_files.extend(files)
        if not next_page or len(all_files) >= MAX_FILES_PER_RUN + current_index:
            break
        page = next_page

    total_found = len(all_files)
    print(f"Found {total_found} files to process")
    sys.stdout.flush()

    if total_found == 0 or current_index >= total_found:
        print("Nothing to process.")
        state["last_page"] = 1
        state["last_index"] = 0
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        return

    # Process files
    files_to_process = all_files[current_index:current_index + MAX_FILES_PER_RUN]

    for i, file_info in enumerate(files_to_process):
        file_path = file_info["path"]
        file_name = file_info["name"]

        print(f"  [{current_index + i + 1}/{total_found}] {file_name}...", end=" ")
        sys.stdout.flush()

        # Read file
        content = get_file_content(file_path)
        if not content:
            print("SKIP (no content)")
            skipped += 1
            log_entries.append(f"SKIP | {file_name} | No content")
            _update_progress(state, current_page, current_index + i + 1, total_moved_total + moved)
            continue

        if len(content.strip()) < 50:
            print("SKIP (empty)")
            skipped += 1
            log_entries.append(f"SKIP | {file_name} | Empty")
            _update_progress(state, current_page, current_index + i + 1, total_moved_total + moved)
            continue

        # Extract category
        category = extract_category(content)
        if not category:
            print("SKIP (no category)")
            skipped += 1
            log_entries.append(f"SKIP | {file_name} | No category")
            _update_progress(state, current_page, current_index + i + 1, total_moved_total + moved)
            continue

        # Build destination path
        folder = CATEGORY_SLUGS.get(category, "other")
        dest_path = f"{folder}/{file_name}"

        # Check if destination exists
        if get_file_sha(dest_path):
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            base_name = file_name.replace(".md", "")
            dest_path = f"{folder}/{timestamp}-{base_name}.md"

        # Move the file
        success = move_file(file_path, dest_path, content)
        if success:
            sid = extract_submission_id(content) or "?"
            print(f"OK → {folder}/")
            moved += 1
            log_entries.append(f"MOVE | {file_name} → {dest_path} | {sid}")
        else:
            print("FAIL")
            errors += 1
            log_entries.append(f"FAIL | {file_name} | Move failed")

        # Save progress every 50 files
        _update_progress(state, current_page, current_index + i + 1, total_moved_total + moved)

    # Final state update
    if current_index + len(files_to_process) >= total_found:
        state["last_page"] = 1
        state["last_index"] = 0
    else:
        state["last_page"] = current_page
        state["last_index"] = current_index + len(files_to_process)
    state["total_moved"] = total_moved_total + moved
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    # Summary
    print("\n" + "=" * 60)
    print(f"THIS RUN: {moved} moved | {skipped} skipped | {errors} errors")
    print(f"TOTAL: {state['total_moved']} moved overall")
    print("=" * 60)

    # Save log
    _save_log(log_entries, moved, skipped, errors)


def _update_progress(state: Dict, page: int, index: int, total: int):
    """Save progress to state file periodically."""
    state["last_page"] = page
    state["last_index"] = index
    state["total_moved"] = total
    state["last_run"] = datetime.now(timezone.utc).isoformat()


def _save_log(log_entries: List[str], moved: int, skipped: int, errors: int):
    """Save run log to knowledge repo."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    log_content = f"# Batch Move Log — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
    log_content += f"# {moved} moved | {skipped} skipped | {errors} errors\n\n"
    log_content += "\n".join(log_entries) if log_entries else "No entries."

    log_path = f"admin/batch-move-log-{timestamp}.md"
    create_github_file(log_path, log_content, f"Move log: {moved} moved")


if __name__ == "__main__":
    run_batch_mover()
