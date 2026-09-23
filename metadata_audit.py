"""
Metadata Audit & Backfill Tool — v2.0
=====================================
Scans knowledge files in the private knowledge repo in batches.
For files missing metadata, writes a legacy entry to entry-metadata.jsonl.
Saves progress and resumes from where it left off on the next run.

This is a COMBINED audit + backfill tool.
- Files WITH metadata: skipped (preserved)
- Files WITHOUT metadata: marked as legacy

Usage:
    python metadata_audit.py

Environment variables needed:
    - GH_TOKEN: GitHub API token
    - KNOWLEDGE_REPO: "org/repo-name"
    - AUDIT_BATCH_SIZE: Files per run (default: 500)

Output:
    - admin/entry-metadata.jsonl (updated with legacy entries)
    - admin/metadata_report.md (updated report)
    - admin/audit-progress.json (resume state)
"""

import os
import sys
import json
import base64
import re
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Set, Tuple
import time


# ===========================================================================
# Configuration
# ===========================================================================

GITHUB_API = "https://api.github.com"
METADATA_FILE_PATH = "admin/entry-metadata.jsonl"
REPORT_REPO_PATH = "admin/metadata_report.md"
PROGRESS_REPO_PATH = "admin/audit-progress.json"

# Batch size — process this many files per run
AUDIT_BATCH_SIZE = int(os.getenv("AUDIT_BATCH_SIZE", "500"))

# Categories to scan
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

# Retry settings
RETRY_COUNT = 3
RETRY_DELAY = 2
REQUEST_TIMEOUT = 15


# ===========================================================================
# GitHub API Helpers
# ===========================================================================

def _github_headers() -> Dict[str, str]:
    token = os.getenv("GH_TOKEN")
    if not token:
        return {"Accept": "application/vnd.github.v3+json"}
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def _get_repo() -> str:
    repo = os.getenv("KNOWLEDGE_REPO")
    if not repo:
        raise ValueError("KNOWLEDGE_REPO environment variable not set")
    return repo


def _github_request(method: str, url: str, **kwargs) -> Optional[requests.Response]:
    headers = _github_headers()
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)

    for attempt in range(RETRY_COUNT):
        try:
            response = requests.request(method, url, headers=headers, **kwargs)

            if response.status_code in [200, 201]:
                return response

            if response.status_code == 404:
                return response

            if response.status_code == 403 and "rate limit" in response.text.lower():
                reset_time = response.headers.get("X-RateLimit-Reset")
                if reset_time:
                    wait_time = max(int(reset_time) - int(time.time()) + 10, 30)
                    print(f"  [Audit] GitHub rate limit. Waiting {wait_time}s...")
                    sys.stdout.flush()
                    time.sleep(wait_time)
                continue

            if response.status_code >= 500:
                print(f"  [Audit] Server error {response.status_code}. Retry {attempt + 1}/{RETRY_COUNT}...")
                time.sleep(RETRY_DELAY * (attempt + 1))
                continue

            return response

        except requests.exceptions.RequestException as e:
            print(f"  [Audit] Request error: {e}. Retry {attempt + 1}/{RETRY_COUNT}...")
            time.sleep(RETRY_DELAY * (attempt + 1))

    return None


def _get_file_content_and_sha(path: str) -> Tuple[Optional[str], Optional[str]]:
    """Get content and SHA of a file from GitHub. Returns (content, sha)."""
    repo = _get_repo()
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    response = _github_request("GET", url)
    if response is None:
        return None, None
    if response.status_code == 404:
        return "", None
    if response.status_code != 200:
        return None, None
    data = response.json()
    content_b64 = data.get("content", "")
    sha = data.get("sha", "")
    if not content_b64:
        return "", sha
    try:
        content = base64.b64decode(content_b64).decode("utf-8")
        return content, sha
    except Exception:
        return None, None


def _get_file_content(path: str) -> Optional[str]:
    content, _ = _get_file_content_and_sha(path)
    return content


def _get_file_sha(path: str) -> Optional[str]:
    _, sha = _get_file_content_and_sha(path)
    return sha


def _list_directory(path: str) -> List[Dict[str, Any]]:
    repo = _get_repo()
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    response = _github_request("GET", url)
    if response is None or response.status_code != 200:
        return []
    data = response.json()
    if isinstance(data, list):
        return data
    return []


def _write_file(path: str, content: str, commit_message: str) -> bool:
    repo = _get_repo()
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    sha = _get_file_sha(path)

    payload = {
        "message": commit_message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    response = _github_request("PUT", url, json=payload)
    return response is not None and response.status_code in [200, 201]


# ===========================================================================
# Progress Tracking
# ===========================================================================

def load_progress() -> Dict[str, Any]:
    content = _get_file_content(PROGRESS_REPO_PATH)
    if not content:
        return {
            "last_audited_category": None,
            "last_audited_index": 0,
            "completed": False,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "total_legacy_written": 0,
            "total_with_metadata": 0,
        }
    try:
        progress = json.loads(content)
        progress.setdefault("total_legacy_written", 0)
        progress.setdefault("total_with_metadata", 0)
        return progress
    except Exception:
        return {
            "last_audited_category": None,
            "last_audited_index": 0,
            "completed": False,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "total_legacy_written": 0,
            "total_with_metadata": 0,
        }


def save_progress(progress: Dict[str, Any]) -> bool:
    content = json.dumps(progress, indent=2)
    message = "Update audit progress"
    return _write_file(PROGRESS_REPO_PATH, content, message)


# ===========================================================================
# Metadata Loading & Writing
# ===========================================================================

def load_metadata() -> Tuple[Dict[str, Dict[str, Any]], str, Optional[str]]:
    """
    Load entry-metadata.jsonl.
    Returns (metadata_dict, raw_content, sha).
    """
    content, sha = _get_file_content_and_sha(METADATA_FILE_PATH)
    if content is None:
        return {}, "", None
    if not content:
        return {}, "", sha

    metadata = {}
    for line in content.strip().split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            sid = entry.get("submission_id", "")
            if sid:
                metadata[sid] = entry
        except json.JSONDecodeError:
            continue

    return metadata, content, sha


def append_legacy_entries(new_entries: List[Dict[str, Any]], existing_content: str, sha: Optional[str]) -> bool:
    """Append legacy entries to entry-metadata.jsonl."""
    if not new_entries:
        return True

    lines = []
    for entry in new_entries:
        lines.append(json.dumps(entry))

    updated_content = existing_content
    if updated_content and not updated_content.endswith("\n"):
        updated_content += "\n"
    updated_content += "\n".join(lines) + "\n"

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = f"Add legacy metadata entries [{timestamp}]"
    return _write_file(METADATA_FILE_PATH, updated_content, message)


# ===========================================================================
# File Scanning
# ===========================================================================

def scan_category(category_slug: str) -> List[Dict[str, Any]]:
    files = []
    items = _list_directory(category_slug)

    for item in items:
        if item.get("type") != "file":
            continue
        if not item.get("name", "").endswith(".md"):
            continue

        files.append({
            "path": item.get("path", ""),
            "name": item.get("name", ""),
            "category_slug": category_slug,
            "size": item.get("size", 0),
        })

    return files


def extract_submission_id_from_filename(filename: str) -> Optional[str]:
    match = re.search(r'GHGPT-\d{4}-\d{4}', filename)
    return match.group(0) if match else None


def extract_submission_id_from_content(content: str) -> Optional[str]:
    match = re.search(r'GHGPT-\d{4}-\d{4}', content)
    return match.group(0) if match else None


def extract_date_from_filename(filename: str) -> Optional[str]:
    """Extract date from filename like 20260719-151240-..."""
    match = re.match(r'^(\d{4})(\d{2})(\d{2})', filename)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month}-{day}"
    return None


def get_file_metadata_info(file_info: Dict[str, Any], metadata: Dict[str, Dict[str, Any]]) -> Tuple[Optional[str], bool]:
    """
    Check if file has metadata.
    Returns (submission_id, has_metadata).
    """
    # Try filename first
    sid = extract_submission_id_from_filename(file_info["name"])
    if sid and sid in metadata:
        return sid, True

    # Try content
    content = _get_file_content(file_info["path"])
    if content:
        sid = extract_submission_id_from_content(content)
        if sid and sid in metadata:
            return sid, True

    return sid, False


# ===========================================================================
# Audit Logic (Batched — Option A)
# ===========================================================================

def run_audit_batch(metadata: Dict[str, Dict[str, Any]], progress: Dict[str, Any]) -> Dict[str, Any]:
    """Run one batch of the audit + backfill."""
    categories = list(CATEGORY_SLUGS.items())

    # Find starting category
    start_category = progress.get("last_audited_category")
    start_index = progress.get("last_audited_index", 0)

    if start_category is None:
        category_start = 0
    else:
        category_start = next(
            (i for i, (name, _) in enumerate(categories) if name == start_category),
            0
        )

    files_processed = 0
    legacy_written = 0
    with_metadata = 0
    new_legacy_entries = []
    category_summary = {}

    print(f"\nProcessing batch of up to {AUDIT_BATCH_SIZE} files...")
    print(f"Starting from: {start_category or 'beginning'} (index {start_index})")
    print("-" * 70)

    for cat_idx in range(category_start, len(categories)):
        category_name, category_slug = categories[cat_idx]

        file_start = start_index if cat_idx == category_start else 0
        files = scan_category(category_slug)
        total_in_category = len(files)
        files_to_process = files[file_start:]

        if not files_to_process:
            continue

        for file_info in files_to_process:
            if files_processed >= AUDIT_BATCH_SIZE:
                break

            sid, has_meta = get_file_metadata_info(file_info, metadata)

            if has_meta:
                with_metadata += 1
            else:
                # Write legacy entry
                legacy_entry = {
                    "submission_id": file_info["path"].replace(".md", ""),
                    "source": "unknown-source",
                    "model": "",
                    "type": "legacy",
                    "date": extract_date_from_filename(file_info["name"]) or "",
                    "category": category_name,
                    "email": "",
                }
                new_legacy_entries.append(legacy_entry)
                legacy_written += 1

            files_processed += 1

        category_summary[category_name] = {
            "total": total_in_category,
            "processed_this_run": min(files_processed, len(files_to_process)),
        }

        if files_processed >= AUDIT_BATCH_SIZE:
            progress["last_audited_category"] = category_name
            progress["last_audited_index"] = file_start + files_processed
            break
        else:
            progress["last_audited_category"] = category_name
            progress["last_audited_index"] = total_in_category

    completed = files_processed < AUDIT_BATCH_SIZE
    if completed:
        progress["completed"] = True

    progress["last_run"] = datetime.now(timezone.utc).isoformat()
    progress["total_legacy_written"] = progress.get("total_legacy_written", 0) + legacy_written
    progress["total_with_metadata"] = progress.get("total_with_metadata", 0) + with_metadata

    return {
        "files_processed": files_processed,
        "with_metadata": with_metadata,
        "legacy_written": legacy_written,
        "new_legacy_entries": new_legacy_entries,
        "category_summary": category_summary,
        "completed": completed,
    }


# ===========================================================================
# Report Generation
# ===========================================================================

def generate_markdown_report(progress: Dict[str, Any], batch_result: Dict[str, Any]) -> str:
    """Generate Markdown report."""
    total_legacy = progress.get("total_legacy_written", 0)
    total_with_meta = progress.get("total_with_metadata", 0)
    total_processed = total_legacy + total_with_meta
    coverage = round((total_with_meta / total_processed * 100) if total_processed > 0 else 0, 2)

    lines = []
    lines.append("# Metadata Audit Report\n\n")
    lines.append(f"**Last Updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n")
    lines.append(f"**Status:** {'✅ Complete' if progress.get('completed') else '⏳ In Progress'}\n\n")

    lines.append("## Summary\n\n")
    lines.append(f"- **Files processed so far:** {total_processed}\n")
    lines.append(f"- **Files with metadata:** {total_with_meta}\n")
    lines.append(f"- **Legacy entries written:** {total_legacy}\n")
    lines.append(f"- **Coverage:** {coverage}%\n\n")

    lines.append("## Progress\n\n")
    lines.append(f"- **Last audited category:** {progress.get('last_audited_category', 'none')}\n")
    lines.append(f"- **Last audited index:** {progress.get('last_audited_index', 0)}\n")
    lines.append(f"- **Completed:** {progress.get('completed', False)}\n\n")

    lines.append("## This Run\n\n")
    lines.append(f"- **Files processed:** {batch_result['files_processed']}\n")
    lines.append(f"- **With metadata:** {batch_result['with_metadata']}\n")
    lines.append(f"- **Legacy entries written:** {batch_result['legacy_written']}\n\n")

    lines.append(f"---\n\n")
    lines.append(f"*Report generated by metadata_audit.py v2.0*\n")

    return "".join(lines)


def save_report_to_repo(report_content: str) -> bool:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = f"Update metadata audit report [{timestamp}]"
    return _write_file(REPORT_REPO_PATH, report_content, message)


# ===========================================================================
# Main
# ===========================================================================

def main():
    print("=" * 70)
    print(f"Metadata Audit & Backfill Tool v2.0 (Batch size: {AUDIT_BATCH_SIZE})")
    print("=" * 70)

    repo = os.getenv("KNOWLEDGE_REPO")
    if not repo:
        print("ERROR: KNOWLEDGE_REPO environment variable not set")
        sys.exit(1)

    if not os.getenv("GH_TOKEN"):
        print("ERROR: GH_TOKEN environment variable not set")
        sys.exit(1)

    print(f"Repo: {repo}")
    print(f"Batch size: {AUDIT_BATCH_SIZE}")

    # Load metadata
    print("\nLoading metadata...")
    metadata, existing_content, metadata_sha = load_metadata()
    print(f"  Loaded {len(metadata)} metadata entries")

    # Load progress
    print("\nLoading progress...")
    progress = load_progress()
    print(f"  Last category: {progress.get('last_audited_category')}")
    print(f"  Last index: {progress.get('last_audited_index')}")
    print(f"  Completed: {progress.get('completed')}")
    print(f"  Total legacy written so far: {progress.get('total_legacy_written', 0)}")

    if progress.get("completed"):
        print("\n✅ Audit is already complete.")
        print("   To re-run, delete admin/audit-progress.json")
        return

    # Run batch
    print("\nRunning batch audit + backfill...")
    batch_result = run_audit_batch(metadata, progress)

    print(f"\nFiles processed this run: {batch_result['files_processed']}")
    print(f"With metadata: {batch_result['with_metadata']}")
    print(f"Legacy entries written: {batch_result['legacy_written']}")

    # Write legacy entries to metadata file
    if batch_result["new_legacy_entries"]:
        print(f"\nAppending {len(batch_result['new_legacy_entries'])} legacy entries to metadata file...")
        success = append_legacy_entries(
            batch_result["new_legacy_entries"],
            existing_content,
            metadata_sha,
        )
        if success:
            print("  ✅ Legacy entries saved")
        else:
            print("  ❌ Failed to save legacy entries")

    # Save progress
    save_progress(progress)
    print(f"\nProgress saved to {PROGRESS_REPO_PATH}")

    # Save report
    report_content = generate_markdown_report(progress, batch_result)
    save_report_to_repo(report_content)
    print(f"Report saved to {REPORT_REPO_PATH}")

    print("\n" + "=" * 70)
    if batch_result["completed"]:
        print("✅ Audit + backfill complete.")
    else:
        print(f"⏳ Batch complete. {batch_result['files_processed']} files processed.")
        print("   Next run continues from where this one stopped.")
    print("=" * 70)


if __name__ == "__main__":
    main()
