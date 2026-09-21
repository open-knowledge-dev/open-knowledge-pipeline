"""
Metadata Audit Tool — v1.1
===========================
Scans all knowledge files in the private knowledge repo and reports
which ones are missing metadata in entry-metadata.jsonl.

This is a READ-ONLY audit tool for the knowledge files.
It writes the report to admin/metadata_report.md in the private repo.

Usage:
    python metadata_audit.py

Environment variables needed:
    - GH_TOKEN: GitHub API token
    - KNOWLEDGE_REPO: "org/repo-name"

Output:
    - Console report with summary
    - admin/metadata_report.md in the knowledge repo (committed)
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
    """Get GitHub API headers with authentication."""
    token = os.getenv("GH_TOKEN")
    if not token:
        return {"Accept": "application/vnd.github.v3+json"}
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def _get_repo() -> str:
    """Get the knowledge repo from environment."""
    repo = os.getenv("KNOWLEDGE_REPO")
    if not repo:
        raise ValueError("KNOWLEDGE_REPO environment variable not set")
    return repo


def _github_request(method: str, url: str, **kwargs) -> Optional[requests.Response]:
    """Make a GitHub API request with retry logic."""
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
                print(f"  [Audit] GitHub server error {response.status_code}. Retry {attempt + 1}/{RETRY_COUNT}...")
                time.sleep(RETRY_DELAY * (attempt + 1))
                continue

            return response

        except requests.exceptions.RequestException as e:
            print(f"  [Audit] Request error: {e}. Retry {attempt + 1}/{RETRY_COUNT}...")
            time.sleep(RETRY_DELAY * (attempt + 1))

    return None


def _get_file_content(path: str) -> Optional[str]:
    """Get content of a file from GitHub."""
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
    """Get SHA of a file from GitHub."""
    repo = _get_repo()
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    response = _github_request("GET", url)
    if response is None or response.status_code != 200:
        return None
    return response.json().get("sha")


def _list_directory(path: str) -> List[Dict[str, Any]]:
    """List contents of a directory in GitHub."""
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
    """Write or update a file in the knowledge repo."""
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
    if response and response.status_code in [200, 201]:
        return True
    return False


# ===========================================================================
# Metadata Loading
# ===========================================================================

def load_metadata() -> Dict[str, Dict[str, Any]]:
    """Load entry-metadata.jsonl and return a dict keyed by submission_id."""
    content = _get_file_content(METADATA_FILE_PATH)
    if not content:
        print(f"  [Audit] WARNING: entry-metadata.jsonl is empty or missing")
        return {}

    metadata = {}
    errors = []

    for i, line in enumerate(content.strip().split("\n"), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            submission_id = entry.get("submission_id", "")
            if submission_id:
                metadata[submission_id] = entry
        except json.JSONDecodeError as e:
            errors.append(f"Line {i}: {e}")

    if errors:
        print(f"  [Audit] WARNING: {len(errors)} invalid lines in metadata file")

    return metadata


# ===========================================================================
# File Scanning
# ===========================================================================

def scan_category(category_slug: str) -> List[Dict[str, Any]]:
    """Scan a category directory and return list of file info."""
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
    """
    Try to extract a submission ID from a filename.
    Filenames may contain GHGPT-XXXX-YYYY anywhere.
    """
    import re
    match = re.search(r'GHGPT-\d{4}-\d{4}', filename)
    if match:
        return match.group(0)
    return None


def extract_submission_id_from_content(content: str) -> Optional[str]:
    """Try to extract submission ID from file content (frontmatter)."""
    import re
    match = re.search(r'GHGPT-\d{4}-\d{4}', content)
    if match:
        return match.group(0)
    return None


def get_file_submission_id(file_info: Dict[str, Any]) -> Optional[str]:
    """Get submission ID from a file — try filename first, then content."""
    # Try filename
    sid = extract_submission_id_from_filename(file_info["name"])
    if sid:
        return sid

    # Try content
    content = _get_file_content(file_info["path"])
    if content:
        sid = extract_submission_id_from_content(content)
        if sid:
            return sid

    return None


# ===========================================================================
# Audit Logic
# ===========================================================================

def audit_category(category_name: str, category_slug: str, metadata: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Audit a single category."""
    print(f"\n--- Auditing: {category_name} ---")

    files = scan_category(category_slug)
    if not files:
        print(f"  No files found")
        return {
            "category": category_name,
            "slug": category_slug,
            "total_files": 0,
            "with_metadata": 0,
            "missing_metadata": 0,
            "missing_ids": [],
        }

    print(f"  Found {len(files)} files")

    with_metadata = 0
    missing_metadata = 0
    missing_ids = []

    for file_info in files:
        sid = get_file_submission_id(file_info)

        if sid is None:
            missing_metadata += 1
            missing_ids.append({
                "path": file_info["path"],
                "reason": "no_submission_id_found",
            })
            continue

        if sid in metadata:
            with_metadata += 1
        else:
            missing_metadata += 1
            missing_ids.append({
                "path": file_info["path"],
                "submission_id": sid,
                "reason": "id_not_in_metadata",
            })

    print(f"  With metadata: {with_metadata}")
    print(f"  Missing metadata: {missing_metadata}")

    return {
        "category": category_name,
        "slug": category_slug,
        "total_files": len(files),
        "with_metadata": with_metadata,
        "missing_metadata": missing_metadata,
        "missing_ids": missing_ids,
    }


def run_audit() -> Dict[str, Any]:
    """Run full audit across all categories."""
    print("=" * 70)
    print("Metadata Audit Tool v1.1")
    print("=" * 70)

    repo = os.getenv("KNOWLEDGE_REPO")
    if not repo:
        print("ERROR: KNOWLEDGE_REPO environment variable not set")
        sys.exit(1)

    if not os.getenv("GH_TOKEN"):
        print("ERROR: GH_TOKEN environment variable not set")
        sys.exit(1)

    print(f"Repo: {repo}")
    print(f"Metadata file: {METADATA_FILE_PATH}")
    print("=" * 70)

    # Load metadata
    print("\nLoading metadata...")
    metadata = load_metadata()
    print(f"  Loaded {len(metadata)} metadata entries")

    # Audit each category
    print("\nAuditing categories...")
    results = []
    for category_name, category_slug in CATEGORY_SLUGS.items():
        result = audit_category(category_name, category_slug, metadata)
        results.append(result)

    # Summary
    total_files = sum(r["total_files"] for r in results)
    total_with_metadata = sum(r["with_metadata"] for r in results)
    total_missing = sum(r["missing_metadata"] for r in results)

    total_metadata_entries = len(metadata)

    print("\n" + "=" * 70)
    print("AUDIT SUMMARY")
    print("=" * 70)
    print(f"Total files in knowledge repo: {total_files}")
    print(f"Total metadata entries: {total_metadata_entries}")
    print(f"Files with metadata: {total_with_metadata}")
    print(f"Files missing metadata: {total_missing}")
    if total_files > 0:
        coverage = (total_with_metadata / total_files) * 100
        print(f"Coverage: {coverage:.1f}%")
    print("=" * 70)

    report = {
        "audit_date": datetime.now(timezone.utc).isoformat(),
        "repo": repo,
        "total_files": total_files,
        "total_metadata_entries": total_metadata_entries,
        "files_with_metadata": total_with_metadata,
        "files_missing_metadata": total_missing,
        "coverage_percent": round((total_with_metadata / total_files * 100) if total_files > 0 else 0, 2),
        "categories": results,
    }

    return report


# ===========================================================================
# Report Generation
# ===========================================================================

def generate_markdown_report(report: Dict[str, Any]) -> str:
    """Generate the Markdown report content."""
    lines = []
    lines.append("# Metadata Audit Report\n\n")
    lines.append(f"**Audit Date:** {report['audit_date']}\n\n")
    lines.append(f"**Repo:** {report['repo']}\n\n")

    lines.append("## Summary\n\n")
    lines.append(f"- **Total files in knowledge repo:** {report['total_files']}\n")
    lines.append(f"- **Total metadata entries:** {report['total_metadata_entries']}\n")
    lines.append(f"- **Files with metadata:** {report['files_with_metadata']}\n")
    lines.append(f"- **Files missing metadata:** {report['files_missing_metadata']}\n")
    lines.append(f"- **Coverage:** {report['coverage_percent']}%\n\n")

    lines.append("## By Category\n\n")
    lines.append("| Category | Total Files | With Metadata | Missing | Coverage |\n")
    lines.append("|----------|-------------|---------------|---------|----------|\n")
    for cat in report["categories"]:
        total = cat["total_files"]
        with_meta = cat["with_metadata"]
        coverage = round((with_meta / total * 100) if total > 0 else 0, 1)
        lines.append(f"| {cat['category']} | {total} | {with_meta} | {cat['missing_metadata']} | {coverage}% |\n")

    lines.append("\n## Missing Metadata Details\n\n")
    for cat in report["categories"]:
        if not cat["missing_ids"]:
            continue
        lines.append(f"\n### {cat['category']} ({len(cat['missing_ids'])} missing)\n\n")
        for item in cat["missing_ids"][:50]:
            lines.append(f"- `{item['path']}` — {item.get('reason', 'unknown')}\n")
        if len(cat["missing_ids"]) > 50:
            lines.append(f"- ... and {len(cat['missing_ids']) - 50} more\n")

    lines.append(f"\n---\n\n")
    lines.append(f"*Report generated by metadata_audit.py v1.1*\n")

    return "".join(lines)


def save_report_to_repo(report: Dict[str, Any]) -> bool:
    """Save report as Markdown to the private knowledge repo."""
    content = generate_markdown_report(report)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = f"Update metadata audit report [{timestamp}]"

    success = _write_file(REPORT_REPO_PATH, content, message)
    if success:
        print(f"\nReport saved to repo: {REPORT_REPO_PATH}")
    else:
        print(f"\nFailed to save report to repo: {REPORT_REPO_PATH}")
    return success


# ===========================================================================
# Main
# ===========================================================================

def main():
    """Main entry point."""
    report = run_audit()

    # Save report to repo
    print("\nSaving report to knowledge repo...")
    save_report_to_repo(report)

    print("\n" + "=" * 70)
    print("Audit complete.")
    print("=" * 70)


if __name__ == "__main__":
    main()
