#!/usr/bin/env python3
"""
Content Rewriter — v2.2
=======================
Rewrites knowledge content to remove banned organizations and terms.
Handles ALL banned organizations.
- Stronger rewrite prompt with explicit instructions
- Retry logic (3 attempts) if banned content remains
- Aggressive banning with exact matches
- CI-compatible
"""

import os
import sys
import re
import json
import base64
import requests
import time
from datetime import datetime
from typing import Optional, List, Dict, Tuple

# ===========================================================================
# Configuration
# ===========================================================================

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
GH_TOKEN = os.getenv("GH_TOKEN", "")
KNOWLEDGE_REPO = os.getenv("KNOWLEDGE_REPO", "")
GITHUB_API = "https://api.github.com"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
REQUEST_TIMEOUT = 90

# CI / non-interactive mode
CI_MODE = os.getenv("CI", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
MAX_FILES = int(os.getenv("MAX_FILES", "10")) if os.getenv("MAX_FILES") else 10

# ===========================================================================
# Banned Organizations — Exact match patterns
# ===========================================================================

# Full organization names — exact matches only (case-insensitive)
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
]

BANNED_TERMS = [
    "development program",
    "aid program",
    "international assistance",
    "foreign aid",
    "development agency",
    "grant",
    "funding",
    "NGO",
    "non-governmental"
]

# Regex patterns to avoid false positives
# e.g., "UN" should match "UN " but not "under" or "university"
def build_banned_patterns() -> List[re.Pattern]:
    """Build regex patterns for banned terms to avoid false positives."""
    patterns = []
    for term in BANNED_ORGS:
        # For short terms like "UN" or "EU", use word boundaries
        if len(term) <= 3:
            patterns.append(re.compile(rf'\b{re.escape(term)}\b', re.IGNORECASE))
        else:
            patterns.append(re.compile(rf'{re.escape(term)}', re.IGNORECASE))
    for term in BANNED_TERMS:
        patterns.append(re.compile(rf'{re.escape(term)}', re.IGNORECASE))
    return patterns

BANNED_PATTERNS = build_banned_patterns()

# ===========================================================================
# Strong Rewrite Prompt
# ===========================================================================

BANNED_ORGS_STRING = ", ".join(BANNED_ORGS)
BANNED_TERMS_STRING = ", ".join(BANNED_TERMS)

REWRITE_PROMPT = (
    f"You are an African knowledge expert. You MUST rewrite the content below to "
    f"REMOVE ALL references to international organizations and external entities.\n\n"
    f"DO NOT mention these organizations at all: {BANNED_ORGS_STRING}\n"
    f"DO NOT mention these terms at all: {BANNED_TERMS_STRING}\n\n"
    f"Rewrite rules:\n"
    f"1. Remove every mention of the above organizations and terms — delete or replace them\n"
    f"2. Never say 'according to WHO' — say 'according to local experts'\n"
    f"3. Never say 'UN program' — say 'community program'\n"
    f"4. Never say 'World Bank' — say 'regional initiative'\n"
    f"5. Never say 'funding' or 'grant' — remove or rewrite without these terms\n"
    f"6. Present all information as African knowledge from local communities\n"
    f"7. Keep all factual information intact\n"
    f"8. Write in plain text. No markdown.\n"
    f"9. At least 400 words.\n\n"
    f"IMPORTANT: After rewriting, check your work. If you see ANY banned term, "
    f"you have failed. Remove them completely."
)

# ===========================================================================
# Banned Content Detection
# ===========================================================================

def detect_banned_content(text: str) -> Tuple[bool, List[str]]:
    """Check if content contains banned organizations or terms using regex."""
    found = []
    for pattern in BANNED_PATTERNS:
        if pattern.search(text):
            # Get the matched term for reporting
            match = pattern.search(text)
            if match:
                found.append(match.group(0))
    # Remove duplicates
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


def update_file_content(path: str, content: str, message: str) -> bool:
    """Update a file in the knowledge repo."""
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    sha = ""
    try:
        response = requests.get(url, headers=_github_headers(), timeout=30)
        if response.status_code == 200:
            sha = response.json().get("sha", "")
    except Exception:
        pass

    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    try:
        response = requests.put(url, json=payload, headers=_github_headers(), timeout=30)
        return response.status_code in [200, 201]
    except Exception as e:
        print(f"  Error updating file: {e}")
        return False


# ===========================================================================
# Content Rewriting with Retry
# ===========================================================================

def rewrite_with_groq(content: str, attempt: int = 0) -> Optional[str]:
    """Rewrite content using Groq."""
    if not GROQ_API_KEY:
        return None

    extra = ""
    if attempt > 0:
        extra = (
            f"\n\nPREVIOUS ATTEMPT FAILED. You still included banned terms. "
            f"Rewrite AGAIN. Remove ALL references to: {BANNED_ORGS_STRING}. "
            f"Be more aggressive. Do NOT mention any international organizations."
        )

    system_prompt = REWRITE_PROMPT + extra

    if len(content) > 8000:
        content = content[:8000]

    user_prompt = f"Rewrite this content. Remove ALL banned organizations and terms:\n\n{content}"

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.4,  # Lower for more consistent output
        "max_tokens": 4000,
    }

    try:
        response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        print(f"  Groq error: {e}")
        return None


def rewrite_with_mistral(content: str, attempt: int = 0) -> Optional[str]:
    """Rewrite content using Mistral (fallback)."""
    if not MISTRAL_API_KEY:
        return None

    extra = ""
    if attempt > 0:
        extra = (
            f"\n\nPREVIOUS ATTEMPT FAILED. You still included banned terms. "
            f"Rewrite AGAIN. Remove ALL references to: {BANNED_ORGS_STRING}."
        )

    system_prompt = REWRITE_PROMPT + extra

    if len(content) > 8000:
        content = content[:8000]

    user_prompt = f"Rewrite this content. Remove ALL banned organizations and terms:\n\n{content}"

    headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "mistral-small-latest",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.4,
        "max_tokens": 4000,
    }

    try:
        response = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        return None
    except Exception as e:
        print(f"  Mistral error: {e}")
        return None


def rewrite_content(content: str) -> Optional[str]:
    """Rewrite content with retry logic (max 3 attempts)."""
    max_retries = 3
    current_content = content

    for attempt in range(max_retries):
        rewritten = None

        if GROQ_API_KEY:
            rewritten = rewrite_with_groq(current_content, attempt)
        elif MISTRAL_API_KEY:
            rewritten = rewrite_with_mistral(current_content, attempt)

        if not rewritten:
            if attempt < max_retries - 1:
                continue
            return None

        # Clean markdown
        rewritten = re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'\1', rewritten)
        rewritten = re.sub(r'^#{1,6}\s+', '', rewritten, flags=re.MULTILINE)
        rewritten = re.sub(r'```[^`]*```', '', rewritten)
        rewritten = re.sub(r'`([^`]+)`', r'\1', rewritten)
        rewritten = re.sub(r'\n{3,}', '\n\n', rewritten)
        rewritten = rewritten.strip()

        # Check if banned content remains
        has_banned, found = detect_banned_content(rewritten)
        if not has_banned:
            return rewritten

        print(f"    ⚠️ Attempt {attempt + 1} still has: {', '.join(found[:5])}")
        current_content = rewritten

    return None


# ===========================================================================
# Main Cleanup
# ===========================================================================

def scan_and_rewrite_directory(path: str, dry_run: bool = True, max_files: int = None) -> Dict:
    """Scan a directory for banned content and rewrite files."""
    results = {
        "scanned": 0,
        "found_banned": 0,
        "rewritten": 0,
        "failed": 0,
        "files": []
    }

    items = get_repo_contents(path)
    if not items:
        print(f"  No items found in {path}")
        return results

    for item in items:
        if results["rewritten"] >= (max_files or 999999):
            break

        if item.get("type") == "dir":
            print(f"  Scanning subdirectory: {item['name']}")
            sub_results = scan_and_rewrite_directory(
                f"{path}/{item['name']}", dry_run, max_files
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

        if dry_run:
            print(f"    [DRY RUN] Would rewrite this file")
            results["files"].append({
                "path": file_path,
                "found": found,
                "action": "would_rewrite"
            })
            continue

        # Rewrite with retry
        rewritten = rewrite_content(content)
        if not rewritten:
            print(f"    ❌ Failed to rewrite after 3 attempts")
            results["failed"] += 1
            continue

        # Final check
        still_banned, still_found = detect_banned_content(rewritten)
        if still_banned:
            print(f"    ❌ Still has banned content: {', '.join(still_found[:5])}")
            results["failed"] += 1
            continue

        # Update file
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"Content rewrite: removed banned organizations [{timestamp}]"
        if update_file_content(file_path, rewritten, message):
            results["rewritten"] += 1
            results["files"].append({
                "path": file_path,
                "found": found,
                "action": "rewritten"
            })
            print(f"    ✅ Rewritten successfully")
        else:
            results["failed"] += 1
            print(f"    ❌ Failed to update file")

        time.sleep(2)

    return results


def main():
    """Main entry point."""
    print("=" * 70)
    print("Content Rewriter v2.2 — Banned Organization Cleanup")
    print("=" * 70)
    print(f"Banned orgs: {len(BANNED_ORGS)}")
    print(f"Banned terms: {len(BANNED_TERMS)}")
    print(f"Groq: {'ACTIVE' if GROQ_API_KEY else 'NOT SET'}")
    print(f"Mistral: {'ACTIVE' if MISTRAL_API_KEY else 'NOT SET'}")
    print(f"Repo: {KNOWLEDGE_REPO}")
    print(f"CI Mode: {CI_MODE}")
    print(f"DRY RUN: {DRY_RUN}")
    print("=" * 70)

    if not GH_TOKEN or not KNOWLEDGE_REPO:
        print("ERROR: GitHub credentials not configured")
        sys.exit(1)

    if not GROQ_API_KEY and not MISTRAL_API_KEY:
        print("ERROR: No AI API keys configured")
        sys.exit(1)

    dry_run = DRY_RUN
    max_files = MAX_FILES

    if not CI_MODE:
        print("\n")
        dry_run_input = input("DRY RUN? (y/n): ").strip().lower()
        dry_run = dry_run_input == "y"

        max_files_input = input("Max files to rewrite (default 10, 0 for all): ").strip()
        try:
            max_files = int(max_files_input) if max_files_input else 10
            if max_files == 0:
                max_files = None
        except ValueError:
            max_files = 10
    else:
        print(f"\n[CI Mode] DRY_RUN={dry_run}, MAX_FILES={max_files}")

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Scanning knowledge repo...")
    print(f"Max files: {max_files or 'ALL'}")
    print("-" * 70)

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
        "rewritten": 0,
        "failed": 0,
        "files": []
    }

    for category in categories:
        print(f"\n--- Scanning {category} ---")
        results = scan_and_rewrite_directory(category, dry_run, max_files)
        for key in total_results:
            if key != "files":
                total_results[key] += results.get(key, 0)
        total_results["files"].extend(results.get("files", []))

        if max_files and total_results["rewritten"] >= max_files:
            print(f"\nReached max files limit ({max_files})")
            break

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Files scanned: {total_results['scanned']}")
    print(f"Files with banned content: {total_results['found_banned']}")
    print(f"Files rewritten: {total_results['rewritten']}")
    print(f"Files failed: {total_results['failed']}")

    if total_results["files"]:
        print(f"\nDetailed log:")
        for f in total_results["files"]:
            status = f.get("action", "unknown")
            if status == "would_rewrite":
                print(f"  [DRY RUN] {f['path']} — found: {', '.join(f['found'][:3])}")
            elif status == "rewritten":
                print(f"  [✅] {f['path']}")
            else:
                print(f"  [❌] {f['path']}")

    print("=" * 70)

    if total_results['failed'] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
