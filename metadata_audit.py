"""
Metadata Audit Tool — v1.2
===========================
Scans knowledge files in the private knowledge repo in batches.
Processes AUDIT_BATCH_SIZE files per run, saves progress, and resumes
from where it left off on the next run.

This is a READ-ONLY audit tool for the knowledge files.
It writes the report to admin/metadata_report.md in the private repo.

Usage:
    python metadata_audit.py

Environment variables needed:
    - GH_TOKEN: GitHub API token
    - KNOWLEDGE_REPO: "org/repo-name"
    - AUDIT_BATCH_SIZE: Number of files to process per run (default: 500)

Output:
    - Console report with summary
    - admin/metadata_report.md in the knowledge repo (committed)
    - admin/audit-progress.json in the knowledge repo (resume state)
"""

import os
import sys
import json
import base64
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


def _get_file_content(path: str) -> Optional[str]:
    repo = _get_repo()
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    response = _github_request("GET", url)
    if response is None:
        return None
    if response.status_code == 404:
        return ""
    if response.status_code != 200:
        return None
    data = response.json()
    content_b64 = data.get("content", "")
    if not content_b64:
        return ""
    try:
        return base64.b64decode(content_b64).decode("utf-8")
    except Exception:
        return None


def _get_file_sha(path: str) -> Optional[str]:
    repo = _get_repo()
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    response = _github_request("GET", url)
    if response is None or response.status_code != 200:
        return None
    return response.json().get("sha")


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
    """Load audit progress from GitHub."""
    content = _get_file_content(PROGRESS_REPO_PATH)
    if not content:
        return {
            "last_audited_category": None,
            "last_audited_index": 0,
            "completed": False,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
    try:
        return json.loads(content)
    except Exception:
        return {
            "last_audited_category": None,
            "last_audited_index": 0,
            "completed": False,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }


def save_progress(progress: Dict[str, Any]) -> bool:
    """Save audit progress to GitHub."""
    content = json.dumps(progress, indent=2)
    message = "Update audit progress"
    return _write_file(PROGRESS_REPO_PATH, content, message)


# ===========================================================================
# Metadata Loading
# ===========================================================================

def load_metadata() -> Dict[str, Dict[str, Any]]:
    content = _get_file_content(METADATA_FILE_PATH)
    if not content:
        print(f"  [Audit] WARNING: entry-metadata.jsonl is empty or missing")
        return {}

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

    return metadata


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
    import re
    match = re.search(r'GHGPT-\d{4}-\d{4}', filename)
    return match.group(0) if match else None


def extract_submission_id_from_content(content: str) -> Optional[str]:
    import re
    match = re.search(r'GHGPT-\d{4}-\d{4}', content)
    return match.group(0) if match else None


def get_file_submission_id(file_info: Dict[str, Any]) -> Optional[str]:
    # Try filename first — no API call needed
    sid = extract_submission_id_from_filename(file_info["name"])
    if sid:
        return sid

    # Only fetch content if filename has no ID
    content = _get_file_content(file_info["path"])
    if content:
        return extract_submission_id_from_content(content)

    return None


# ===========================================================================
# Audit Logic (Batched)
# ===========================================================================

def run_audit_batch(metadata: Dict[str, Dict[str, Any]], progress: Dict[str, Any]) -> Dict[str, Any]:
    """Run one batch of the audit."""
    categories = list(CATEGORY_SLUGS.items())

    # Find the starting category
    start_category = progress.get("last_audited_category")
    start_index = progress.get("last_audited_index", 0)

    if start_category is None:
        category_start = 0
    else:
        category_start = next(
            (i for i, (name, _) in enumerate(categories) if name == start_category),
            0
        )

    files_processed_this_run = 0
    all_results = []
    completed = False

    print(f"\nProcessing batch of up to {AUDIT_BATCH_SIZE} files...")
    print(f"Starting from: {start_category or 'beginning'} (index {start_index})")
    print("-" * 70)

    for cat_idx in range(category_start, len(categories)):
        category_name, category_slug = categories[cat_idx]

        # Skip to start index if this is the starting category
        file_start = start_index if cat_idx == category_start else 0

        files = scan_category(category_slug)
        total_files_in_category = len(files)

        # Filter out already-processed files
        files_to_process = files[file_start:]

        if not files_to_process:
            continue

        category_result = {
            "category": category_name,
            "slug": category_slug,
            "total_files": total_files_in_category,
            "with_metadata": 0,
            "missing_metadata": 0,
            "missing_ids": [],
        }

        for file_info in files_to_process:
            if files_processed_this_run >= AUDIT_BATCH_SIZE:
                break

            sid = get_file_submission_id(file_info)

            if sid is None:
                category_result["missing_metadata"] += 1
                category_result["missing_ids"].append({
                    "path": file_info["path"],
                    "reason": "no_submission_id_found",
                })
            elif sid in metadata:
                category_result["with_metadata"] += 1
            else:
                category_result["missing_metadata"] += 1
                category_result["missing_ids"].append({
                    "path": file_info["path"],
                    "submission_id": sid,
                    "reason": "id_not_in_metadata",
                })

            files_processed_this_run += 1

        all_results.append(category_result)

        # Update progress
        if files_processed_this_run >= AUDIT_BATCH_SIZE:
            progress["last_audited_category"] = category_name
            progress["last_audited_index"] = file_start + len(files_to_process[:files_processed_this_run])
            break
        else:
            # Move to next category
            progress["last_audited_category"] = category_name
            progress["last_audited_index"] = total_files_in_category

    if files_processed_this_run < AUDIT_BATCH_SIZE:
        completed = True
        progress["completed"] = True

    progress["last_run"] = datetime.now(timezone.utc).isoformat()

    return {
        "files_processed_this_run": files_processed_this_run,
        "category_results": all_results,
        "completed": completed,
    }


# ===========================================================================
# Report Generation
# ===========================================================================

def generate_markdown_report(
    all_category_results: List[Dict[str, Any]],
    metadata_count: int,
    completed: bool,
    progress: Dict[str, Any],
) -> str:
    """Generate the Markdown report."""

    total_files = sum(r["total_files"] for r in all_category_results)
    total_with_metadata = sum(r["with_metadata"] for r in all_category_results)
    total_missing = sum(r["missing_metadata"] for r in all_category_results)
    coverage = round((total_with_metadata / total_files * 100) if total_files > 0 else 0, 2)

    lines = []
    lines.append("# Metadata Audit Report\n\n")
    lines.append(f"**Last Updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n")
    lines.append(f"**Status:** {'✅ Complete' if completed else '⏳ In Progress'}\n\n")

    lines.append("## Summary\n\n")
    lines.append(f"- **Total files scanned:** {total_files}\n")
    lines.append(f"- **Total metadata entries:** {metadata_count}\n")
    lines.append(f"- **Files with metadata:** {total_with_metadata}\n")
    lines.append(f"- **Files missing metadata:** {total_missing}\n")
    lines.append(f"- **Coverage:** {coverage}%\n\n")

    lines.append("## Progress\n\n")
    lines.append(f"- **Last audited category:** {progress.get('last_audited_category', 'none')}\n")
    lines.append(f"- **Last audited index:** {progress.get('last_audited_index', 0)}\n")
    lines.append(f"- **Completed:** {progress.get('completed', False)}\n\n")

    lines.append("## By Category\n\n")
    lines.append("| Category | Total Files | With Metadata | Missing | Coverage |\n")
    lines.append("|----------|-------------|---------------|---------|----------|\n")
    for cat in all_category_results:
        total = cat["total_files"]
        with_meta = cat["with_metadata"]
        cov = round((with_meta / total * 100) if total > 0 else 0, 1)
        lines.append(f"| {cat['category']} | {total} | {with_meta} | {cat['missing_metadata']} | {cov}% |\n")

    lines.append(f"\n---\n\n")
    lines.append(f"*Report generated by metadata_audit.py v1.2*\n")

    return "".join(lines)


def save_report_to_repo(report_content: str) -> bool:
    """Save report as Markdown to the private knowledge repo."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = f"Update metadata audit report [{timestamp}]"
    return _write_file(REPORT_REPO_PATH, report_content, message)


# ===========================================================================
# Main
# ===========================================================================

def main():
    print("=" * 70)
    print(f"Metadata Audit Tool v1.2 (Batch size: {AUDIT_BATCH_SIZE})")
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
    metadata = load_metadata()
    print(f"  Loaded {len(metadata)} metadata entries")

    # Load progress
    print("\nLoading progress...")
    progress = load_progress()
    print(f"  Last category: {progress.get('last_audited_category')}")
    print(f"  Last index: {progress.get('last_audited_index')}")
    print(f"  Completed: {progress.get('completed')}")

    if progress.get("completed"):
        print("\n✅ Audit is already complete.")
        print("   To re-run, delete admin/audit-progress.json")
        return

    # Run batch
    print("\nRunning batch audit...")
    batch_result = run_audit_batch(metadata, progress)

    print(f"\nFiles processed this run: {batch_result['files_processed_this_run']}")

    # Save progress
    save_progress(progress)
    print(f"Progress saved to {PROGRESS_REPO_PATH}")

    # Generate report from all category results
    # For simplicity, save the latest batch results as the current report
    report_content = generate_markdown_report(
        all_category_results=batch_result["category_results"],
        metadata_count=len(metadata),
        completed=batch_result["completed"],
        progress=progress,
    )

    save_report_to_repo(report_content)
    print(f"Report saved to {REPORT_REPO_PATH}")

    print("\n" + "=" * 70)
    if batch_result["completed"]:
        print("✅ Audit complete.")
    else:
        print(f"⏳ Batch complete. {AUDIT_BATCH_SIZE} files processed.")
        print("   Next run will continue from where this one stopped.")
    print("=" * 70)


if __name__ == "__main__":
    main()
