"""
Move Tainted Files to Issues — Daily Scanner
Scans all categories in the private repo for banned content.
Moves tainted files to issues/ folder.
Deletes the original after successful move.
"""

import os
import sys
import re
import json
import base64
import requests
from datetime import datetime
from typing import Optional, List, Dict, Tuple

# ===========================================================================
# Configuration
# ===========================================================================

GH_TOKEN = os.getenv("GH_TOKEN", "")
KNOWLEDGE_REPO = os.getenv("KNOWLEDGE_REPO", "")
GITHUB_API = "https://api.github.com"

CI_MODE = os.getenv("CI", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# ===========================================================================
# Banned Organizations
# ===========================================================================

BANNED_ORGS = [
    "FAO", "Food and Agriculture Organization",
    "WHO", "World Health Organization",
    "UN", "United Nations",
    "World Bank", "IMF", "International Monetary Fund",
    "UNDP", "UNESCO", "UNICEF",
    "USAID", "DFID", "GIZ",
    "World Food Programme", "WFP",
    "International Labour Organization", "ILO",
    "World Trade Organization", "WTO",
    "African Development Bank", "AfDB",
    "European Union",
]

BANNED_TERMS = [
    "development program", "aid program", "international assistance",
    "foreign aid", "development agency", "grant", "funding", "NGO",
    "non-governmental"
]


def build_banned_patterns() -> List[re.Pattern]:
    patterns = []
    for term in BANNED_ORGS:
        if len(term) <= 3:
            patterns.append(re.compile(rf'\b{re.escape(term)}\b', re.IGNORECASE))
        else:
            patterns.append(re.compile(rf'{re.escape(term)}', re.IGNORECASE))
    for term in BANNED_TERMS:
        patterns.append(re.compile(rf'{re.escape(term)}', re.IGNORECASE))
    return patterns

BANNED_PATTERNS = build_banned_patterns()


def detect_banned_content(text: str) -> Tuple[bool, List[str]]:
    found = []
    for pattern in BANNED_PATTERNS:
        if pattern.search(text):
            match = pattern.search(text)
            if match:
                found.append(match.group(0))
    found = list(set(found))
    return len(found) > 0, found


# ===========================================================================
# GitHub Operations
# ===========================================================================

def _github_headers() -> Dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GH_TOKEN:
        headers["Authorization"] = f"token {GH_TOKEN}"
    return headers


def get_repo_contents(path: str) -> List[Dict]:
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    try:
        response = requests.get(url, headers=_github_headers(), timeout=30)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        print(f"  Error getting contents: {e}")
        return []


def get_file_content(path: str) -> Optional[str]:
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    try:
        response = requests.get(url, headers=_github_headers(), timeout=30)
        if response.status_code == 200:
            data = response.json()
            if data.get("content"):
                return base64.b64decode(data["content"]).decode("utf-8")
        return None
    except Exception as e:
        print(f"  Error getting file: {e}")
        return None


def get_file_sha(path: str) -> Optional[str]:
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    try:
        response = requests.get(url, headers=_github_headers(), timeout=30)
        if response.status_code == 200:
            return response.json().get("sha")
        return None
    except Exception:
        return None


def create_file(path: str, content: str, message: str) -> bool:
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }
    try:
        response = requests.put(url, json=payload, headers=_github_headers(), timeout=30)
        return response.status_code in [200, 201]
    except Exception as e:
        print(f"  Error creating file: {e}")
        return False


def delete_file(path: str, message: str) -> bool:
    sha = get_file_sha(path)
    if not sha:
        return False

    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    payload = {
        "message": message,
        "sha": sha,
        "branch": "main",
    }

    try:
        response = requests.delete(url, json=payload, headers=_github_headers(), timeout=30)
        return response.status_code == 200
    except Exception as e:
        print(f"  Error deleting file: {e}")
        return False


def move_file(source_path: str, dest_path: str, dry_run: bool = True) -> bool:
    if dry_run:
        return True

    content = get_file_content(source_path)
    if not content:
        return False

    if not create_file(dest_path, content, f"Move tainted file: {source_path}"):
        return False

    if not delete_file(source_path, f"Moved to issues/: {dest_path}"):
        return False

    return True


# ===========================================================================
# Scan and Move
# ===========================================================================

def scan_and_move_directory(path: str, dry_run: bool = True, issues_path: str = "issues") -> Dict:
    results = {
        "scanned": 0,
        "found_banned": 0,
        "moved": 0,
        "failed": 0,
        "files": []
    }

    items = get_repo_contents(path)
    if not items:
        print(f"  No items found in {path}")
        return results

    for item in items:
        if item.get("type") == "dir":
            if item["name"] == "issues":
                continue
            print(f"  Scanning subdirectory: {item['name']}")
            sub_results = scan_and_move_directory(
                f"{path}/{item['name']}", dry_run, issues_path
            )
            for key in results:
                if key != "files":
                    results[key] += sub_results.get(key, 0)
            results["files"].extend(sub_results.get("files", []))
            continue

        if not item.get("name", "").endswith(".md"):
            continue

        file_path = item["path"]
        print(f"\n  Checking: {file_path}")

        content = get_file_content(file_path)
        if not content:
            print(f"    ⚠️ Could not read file")
            continue

        results["scanned"] += 1

        has_banned, found = detect_banned_content(content)
        if not has_banned:
            print(f"    ✅ No banned content")
            continue

        results["found_banned"] += 1
        print(f"    ⚠️ Found banned content: {', '.join(found[:5])}")

        filename = item["name"]
        dest_path = f"{issues_path}/{filename}"

        if dry_run:
            print(f"    [DRY RUN] Would move to: {dest_path}")
            results["files"].append({
                "source": file_path,
                "dest": dest_path,
                "found": found,
                "action": "would_move"
            })
            continue

        if move_file(file_path, dest_path, dry_run):
            results["moved"] += 1
            results["files"].append({
                "source": file_path,
                "dest": dest_path,
                "found": found,
                "action": "moved"
            })
            print(f"    ✅ Moved to: {dest_path}")
        else:
            results["failed"] += 1
            print(f"    ❌ Failed to move")

    return results


def main():
    print("=" * 70)
    print("Move Tainted Files to Issues v1.0")
    print("=" * 70)
    print(f"Banned orgs: {len(BANNED_ORGS)}")
    print(f"Repo: {KNOWLEDGE_REPO}")
    print(f"DRY RUN: {DRY_RUN}")
    print("=" * 70)

    if not GH_TOKEN or not KNOWLEDGE_REPO:
        print("ERROR: GitHub credentials not configured")
        sys.exit(1)

    categories = [
        "agriculture_farming", "business_finance", "culture_traditions",
        "education_learning", "health_medicine", "technology_innovation",
        "tourism_travel", "history_heritage", "food_cuisine",
        "music_dance", "language_proverbs", "religion_spirituality",
        "sports_games", "fashion_textiles", "environment_nature",
        "governance_leadership", "family_relationships", "arts_crafts",
        "science_innovation", "other"
    ]

    total_results = {
        "scanned": 0,
        "found_banned": 0,
        "moved": 0,
        "failed": 0,
        "files": []
    }

    print("\nScanning all categories...\n")
    print("-" * 70)

    for category in categories:
        print(f"\n--- Scanning {category} ---")
        results = scan_and_move_directory(category, DRY_RUN)
        for key in total_results:
            if key != "files":
                total_results[key] += results.get(key, 0)
        total_results["files"].extend(results.get("files", []))

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Files scanned: {total_results['scanned']}")
    print(f"Files with banned content: {total_results['found_banned']}")
    print(f"Files moved to issues/: {total_results['moved']}")
    print(f"Files failed: {total_results['failed']}")

    if total_results["files"]:
        print("\nFile list:")
        for f in total_results["files"]:
            action = f.get("action", "unknown")
            if action == "would_move":
                print(f"  [DRY RUN] {f['source']} → {f['dest']}")
            elif action == "moved":
                print(f"  [MOVED] {f['source']} → {f['dest']}")

    print("=" * 70)

    if total_results["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
