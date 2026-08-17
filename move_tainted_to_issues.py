#!/usr/bin/env python3
"""
Move Tainted Files to Issues — v2.0
====================================
Scans all categories in the private repo for banned content.
Moves tainted files to issues/ folder.
Deletes the original after successful move.
Runs daily at 4:00 AM UTC.
"""

import os
import sys
import re
import base64
import requests
import time
from datetime import datetime
from typing import Optional, List, Dict, Tuple

# ===========================================================================
# Configuration
# ===========================================================================

GH_TOKEN = os.getenv("GH_TOKEN", "")
KNOWLEDGE_REPO = os.getenv("KNOWLEDGE_REPO", "")
GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT = 60
RETRY_COUNT = 3
RETRY_DELAY = 2

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
        for match in pattern.finditer(text):
            found.append(match.group(0))
    found = list(set(found))
    return len(found) > 0, found


# ===========================================================================
# GitHub Operations with Retry
# ===========================================================================

def _github_headers() -> Dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GH_TOKEN:
        headers["Authorization"] = f"token {GH_TOKEN}"
    return headers


def api_request(method: str, url: str, **kwargs) -> Optional[requests.Response]:
    for attempt in range(RETRY_COUNT):
        try:
            response = requests.request(
                method, url,
                headers=_github_headers(),
                timeout=REQUEST_TIMEOUT,
                **kwargs
            )
            if response.status_code in [200, 201]:
                return response
            if response.status_code == 404:
                return response
            if response.status_code == 403 and 'rate limit' in response.text.lower():
                reset_time = response.headers.get('X-RateLimit-Reset', '')
                if reset_time:
                    wait_time = max(int(reset_time) - int(time.time()) + 10, 30)
                    print(f"    Rate limit. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                continue
            if response.status_code >= 500:
                print(f"    Server error {response.status_code}. Retry {attempt + 1}/{RETRY_COUNT}...")
                time.sleep(RETRY_DELAY * (attempt + 1))
                continue
            return response
        except requests.exceptions.RequestException as e:
            print(f"    Request error: {e}. Retry {attempt + 1}/{RETRY_COUNT}...")
            time.sleep(RETRY_DELAY * (attempt + 1))
    return None


def get_repo_contents(path: str) -> List[Dict]:
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    response = api_request("GET", url)
    if response and response.status_code == 200:
        return response.json()
    return []


def get_file_content(path: str) -> Optional[str]:
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    response = api_request("GET", url)
    if response and response.status_code == 200:
        data = response.json()
        if data.get("content"):
            return base64.b64decode(data["content"]).decode("utf-8")
    return None


def get_file_sha(path: str) -> Optional[str]:
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    response = api_request("GET", url)
    if response and response.status_code == 200:
        return response.json().get("sha")
    return None


def create_file(path: str, content: str, message: str) -> bool:
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }
    response = api_request("PUT", url, json=payload)
    return response is not None and response.status_code in [200, 201]


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
    response = api_request("DELETE", url, json=payload)
    return response is not None and response.status_code == 200


def move_file(source_path: str, dest_path: str) -> Tuple[bool, str]:
    content = get_file_content(source_path)
    if not content:
        return False, "Could not read source file"

    if not create_file(dest_path, content, f"Move tainted file: {source_path}"):
        return False, "Could not create destination file"

    if not delete_file(source_path, f"Moved to issues/: {dest_path}"):
        return False, "Could not delete source file"

    return True, "Moved successfully"


# ===========================================================================
# Main Logic
# ===========================================================================

def process_category(path: str) -> Dict:
    results = {
        "scanned": 0,
        "found_banned": 0,
        "moved": 0,
        "failed": 0,
        "errors": []
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
            sub_results = process_category(f"{path}/{item['name']}")
            for key in results:
                if key != "errors":
                    results[key] += sub_results.get(key, 0)
            results["errors"].extend(sub_results.get("errors", []))
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
        dest_path = f"issues/{filename}"

        success, message = move_file(file_path, dest_path)
        if success:
            results["moved"] += 1
            print(f"    ✅ Moved to: {dest_path}")
        else:
            results["failed"] += 1
            error_msg = f"{file_path}: {message}"
            results["errors"].append(error_msg)
            print(f"    ❌ {message}")

    return results


def main():
    print("=" * 70)
    print("Move Tainted Files to Issues v2.0")
    print("=" * 70)
    print(f"Banned orgs: {len(BANNED_ORGS)}")
    print(f"Repo: {KNOWLEDGE_REPO}")
    print("=" * 70)

    if not GH_TOKEN or not KNOWLEDGE_REPO:
        print("ERROR: GitHub credentials not configured")
        print("  GH_TOKEN: " + ("SET" if GH_TOKEN else "MISSING"))
        print("  KNOWLEDGE_REPO: " + ("SET" if KNOWLEDGE_REPO else "MISSING"))
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
        "errors": []
    }

    print("\nScanning all categories...\n")
    print("-" * 70)

    for category in categories:
        print(f"\n--- Scanning {category} ---")
        results = process_category(category)
        for key in total_results:
            if key != "errors":
                total_results[key] += results.get(key, 0)
        total_results["errors"].extend(results.get("errors", []))

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Files scanned: {total_results['scanned']}")
    print(f"Files with banned content: {total_results['found_banned']}")
    print(f"Files moved to issues/: {total_results['moved']}")
    print(f"Files failed: {total_results['failed']}")

    if total_results["errors"]:
        print("\nErrors:")
        for error in total_results["errors"]:
            print(f"  ❌ {error}")

    print("=" * 70)

    if total_results["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
