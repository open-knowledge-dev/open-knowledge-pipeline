#!/usr/bin/env python3
"""
Content Cleanup — v1.0
=======================
ONE-TIME SCRIPTS — Scans ALL existing knowledge in the private repo.
Detects banned organizations and terms.
Generates a report of all files that need rewriting.

This is a SCANNER only — use content_rewriter.py to actually rewrite.

Run this ONCE to identify all problematic content.
"""

import os
import sys
import json
import base64
import requests
import re
from datetime import datetime
from typing import Optional, List, Dict, Tuple

# ===========================================================================
# Configuration
# ===========================================================================

GH_TOKEN = os.getenv("GH_TOKEN", "")
KNOWLEDGE_REPO = os.getenv("KNOWLEDGE_REPO", "")
GITHUB_API = "https://api.github.com"

# ===========================================================================
# Banned Organizations
# ===========================================================================

BANNED_ORGS = [
    "FAO",
    "Food and Agriculture Organization",
    "WHO",
    "World Health Organization",
    "UN",
    "United Nations",
    "World Bank",
    "IMF",
    "International Monetary Fund",
    "UNDP",
    "UNESCO",
    "UNICEF",
    "USAID",
    "DFID",
    "GIZ",
    "World Food Programme",
    "WFP",
    "International Labour Organization",
    "ILO",
    "World Trade Organization",
    "WTO",
    "African Development Bank",
    "AfDB",
    "European Union",
    "EU"
]

BANNED_TERMS = [
    "development program", "aid program", "international assistance",
    "foreign aid", "development agency", "grant", "funding", "NGO",
    "non-governmental"
]

# ===========================================================================
# GitHub Operations
# ===========================================================================

def _github_headers() -> Dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GH_TOKEN:
        headers["Authorization"] = f"token {GH_TOKEN}"
    return headers


def get_repo_contents(path: str) -> List[Dict]:
    """Get contents of a directory in the knowledge repo."""
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
    """Get content of a file from the knowledge repo."""
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


# ===========================================================================
# Content Detection
# ===========================================================================

def detect_banned_content(text: str) -> Tuple[bool, List[str]]:
    """Check if content contains banned organizations or terms."""
    text_lower = text.lower()
    found = []
    for org in BANNED_ORGS:
        if org.lower() in text_lower:
            found.append(org)
    for term in BANNED_TERMS:
        if term in text_lower:
            found.append(term)
    return len(found) > 0, found


def scan_file(file_path: str) -> Dict:
    """Scan a single file for banned content."""
    content = get_file_content(file_path)
    if not content:
        return {"path": file_path, "error": "could_not_read"}

    has_banned, found = detect_banned_content(content)
    return {
        "path": file_path,
        "has_banned": has_banned,
        "found": found if has_banned else [],
        "size": len(content),
        "word_count": len(content.split())
    }


def scan_directory(path: str, results: List[Dict]) -> None:
    """Recursively scan a directory."""
    items = get_repo_contents(path)
    if not items:
        return

    for item in items:
        if item.get("type") == "dir":
            scan_directory(f"{path}/{item['name']}", results)
            continue

        if not item.get("name", "").endswith(".md"):
            continue

        file_path = item["path"]
        result = scan_file(file_path)
        if result.get("has_banned"):
            results.append(result)
            print(f"  ⚠️ {file_path} — found: {', '.join(result['found'])}")
        else:
            print(f"  ✅ {file_path}")


# ===========================================================================
# Main
# ===========================================================================

def main():
    """Main entry point."""
    print("=" * 70)
    print("Content Cleanup v1.0 — Banned Content Scanner")
    print("=" * 70)
    print(f"Banned orgs: {len(BANNED_ORGS)}")
    print(f"Banned terms: {len(BANNED_TERMS)}")
    print(f"Repo: {KNOWLEDGE_REPO}")
    print("=" * 70)

    if not GH_TOKEN or not KNOWLEDGE_REPO:
        print("ERROR: GitHub credentials not configured")
        return

    categories = [
        "agriculture_farming", "business_finance", "culture_traditions",
        "education_learning", "health_medicine", "technology_innovation",
        "tourism_travel", "history_heritage", "food_cuisine",
        "music_dance", "language_proverbs", "religion_spirituality",
        "sports_games", "fashion_textiles", "environment_nature",
        "governance_leadership", "family_relationships", "arts_crafts",
        "science_innovation", "other"
    ]

    all_results = []
    total_files = 0
    banned_files = 0

    print("\nScanning all categories...\n")
    print("-" * 70)

    for category in categories:
        print(f"\n--- {category} ---")
        scan_directory(category, all_results)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    # Count by category
    by_category = {}
    for result in all_results:
        parts = result["path"].split("/")
        category = parts[0] if parts else "unknown"
        by_category.setdefault(category, []).append(result)

    total_files = 0
    for category, files in by_category.items():
        total_files += len(files)
        print(f"{category}: {len(files)} files with banned content")

    print("-" * 70)
    print(f"TOTAL: {total_files} files with banned content")

    if all_results:
        print("\nDetailed list of affected files:")
        for result in all_results:
            print(f"  {result['path']}")
            print(f"    Found: {', '.join(result['found'])}")
            print(f"    Words: {result['word_count']}")

        # Save to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"banned_content_report_{timestamp}.json"
        with open(report_file, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"\nReport saved to: {report_file}")

        print("\n" + "=" * 70)
        print("NEXT STEPS:")
        print("1. Run content_rewriter.py to rewrite these files")
        print("2. Or manually review and edit")
        print("=" * 70)

    print("=" * 70)


if __name__ == "__main__":
    main()
