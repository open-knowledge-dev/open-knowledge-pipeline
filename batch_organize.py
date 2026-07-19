"""
Ghana-GPT Batch Organizer — Security Scan + Category Move
===========================================================
Processes ALL pending files in one pass:
1. Security scan (same patterns as security_scanner.py)
2. CRITICAL findings → stays in pending/ for manual review
3. Clean files → extracted to correct category folder
4. Stores filename in Supabase

Runs via GitHub Actions. Handles 660,000+ files.
"""

import os
import sys
import re
import base64
import json
import requests
from datetime import datetime, timezone

print("[INIT] Starting batch organizer...")
sys.stdout.flush()

# ============================================================
# Configuration
# ============================================================

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GITHUB_KNOWLEDGE_REPO = os.getenv("GITHUB_KNOWLEDGE_REPO", "ghana-gpt/ghana-gpt-knowledge")

if not all([GITHUB_TOKEN, SUPABASE_URL, SUPABASE_KEY]):
    print("ERROR: Missing environment variables.")
    sys.exit(1)

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

from supabase import create_client
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Category mapping (same as main.py)
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

# ============================================================
# Security Patterns (Same as security_scanner.py)
# ============================================================

CRITICAL_PATTERNS = {
    "script_tag": re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL),
    "nested_script": re.compile(r'<[^>]*script[^>]*>[^<]*<[^>]*script[^>]*>', re.IGNORECASE),
    "html_entity_script": re.compile(r'&#(?:60|x3c);\s*script\s*&#(?:62|x3e);', re.IGNORECASE),
    "php_tag": re.compile(r'<\?php', re.IGNORECASE),
    "eval_call": re.compile(r'eval\s*\(', re.IGNORECASE),
    "eval_spaced": re.compile(r'eval\s+\(', re.IGNORECASE),
    "eval_mixed": re.compile(r'[eE][vV][aA][lL]\s*\(', re.IGNORECASE),
    "exec_call": re.compile(r'exec\s*\(', re.IGNORECASE),
    "system_call": re.compile(r'system\s*\(|shell_exec\s*\(|popen\s*\(', re.IGNORECASE),
    "base64_large": re.compile(r'[A-Za-z0-9+/]{100,}={0,2}'),
    "sql_injection": re.compile(r"UNION\s+(?:ALL\s+)?SELECT|DROP\s+TABLE", re.IGNORECASE),
    "iframe_tag": re.compile(r'<iframe[^>]*>', re.IGNORECASE),
    "obfuscated_js": re.compile(r'(?:fromCharCode|unescape\s*\(|\\x[0-9a-fA-F]{2})', re.IGNORECASE),
}


def security_scan(content: str) -> list:
    """Check content for critical patterns. Returns list of findings."""
    findings = []
    for name, pattern in CRITICAL_PATTERNS.items():
        if pattern.search(content):
            findings.append(name)
    return findings


# ============================================================
# GitHub Helpers
# ============================================================

def list_all_pending_files():
    """Get ALL .md file paths from pending/ with pagination."""
    all_files = []
    page = 1
    while True:
        url = f"{GITHUB_API}/repos/{GITHUB_KNOWLEDGE_REPO}/contents/pending"
        params = {"page": page, "per_page": 100}
        response = requests.get(url, headers=GITHUB_HEADERS, params=params, timeout=30)
        if response.status_code != 200:
            break
        data = response.json()
        if not data:
            break
        for item in data:
            if item["name"].endswith(".md"):
                all_files.append(item["path"])
        if len(data) < 100:
            break
        page += 1
    return all_files


def get_file_content(path: str) -> str:
    url = f"{GITHUB_API}/repos/{GITHUB_KNOWLEDGE_REPO}/contents/{path}"
    response = requests.get(url, headers=GITHUB_HEADERS, timeout=15)
    if response.status_code == 200:
        data = response.json()
        content_b64 = data.get("content", "")
        if content_b64:
            return base64.b64decode(content_b64).decode("utf-8", errors="ignore")
    return ""


def get_file_sha(path: str) -> str:
    url = f"{GITHUB_API}/repos/{GITHUB_KNOWLEDGE_REPO}/contents/{path}"
    try:
        response = requests.get(url, headers=GITHUB_HEADERS, timeout=15)
        if response.status_code == 200:
            return response.json().get("sha", "")
    except Exception:
        pass
    return ""


def move_file(source_path: str, dest_path: str, content: str) -> bool:
    """Move file from source to destination in GitHub."""
    # Create at destination
    create_url = f"{GITHUB_API}/repos/{GITHUB_KNOWLEDGE_REPO}/contents/{dest_path}"
    create_payload = {
        "message": f"Batch organize: {source_path}",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }
    try:
        r = requests.put(create_url, json=create_payload, headers=GITHUB_HEADERS, timeout=15)
        if r.status_code not in [200, 201]:
            return False

        # Delete source
        sha = get_file_sha(source_path)
        if sha:
            delete_url = f"{GITHUB_API}/repos/{GITHUB_KNOWLEDGE_REPO}/contents/{source_path}"
            delete_payload = {"message": f"Batch remove: {source_path}", "sha": sha, "branch": "main"}
            requests.delete(delete_url, json=delete_payload, headers=GITHUB_HEADERS, timeout=15)
        return True
    except Exception:
        return False


# ============================================================
# Content Parsers
# ============================================================

def extract_category(content: str) -> str:
    """Extract category from file content."""
    match = re.search(r'\*\*Category:\*\*\s*(.+)', content)
    if match:
        return match.group(1).strip()
    return "Other"


def extract_submission_id(content: str) -> str:
    """Extract submission ID from content."""
    match = re.search(r'GHGPT-\d{4}-\d{4}', content)
    return match.group(0) if match else ""


def extract_topic(content: str) -> str:
    """Extract topic from content."""
    match = re.search(r'^#\s+(.+)', content, re.MULTILINE)
    if match:
        return match.group(1).strip()[:80]
    return "untitled"


# ============================================================
# Main Logic
# ============================================================

def organize_all():
    print("=" * 60)
    print("Batch Organizer — Security Scan + Category Move")
    print("=" * 60)
    sys.stdout.flush()

    print("\n[1/3] Listing all pending files...")
    sys.stdout.flush()
    pending_files = list_all_pending_files()
    total = len(pending_files)
    print(f"Found {total} files")
    sys.stdout.flush()

    if total == 0:
        print("No files to process.")
        return

    moved = 0
    flagged = 0
    failed = 0
    skipped = 0

    print(f"\n[2/3] Processing {total} files...")
    sys.stdout.flush()

    for i, filepath in enumerate(pending_files):
        # Progress every 500 files
        if i % 500 == 0 and i > 0:
            print(f"  Progress: {i}/{total} | Moved: {moved} | Flagged: {flagged} | Failed: {failed}")
            sys.stdout.flush()

        # Read content
        content = get_file_content(filepath)
        if not content:
            failed += 1
            continue

        # Security scan
        findings = security_scan(content)
        if findings:
            flagged += 1
            if flagged <= 50:  # Only log first 50 to avoid spam
                print(f"  🚨 FLAGGED: {filepath} — {', '.join(findings)}")
            continue

        # Extract metadata
        category = extract_category(content)
        submission_id = extract_submission_id(content)
        topic = extract_topic(content)

        if not submission_id:
            skipped += 1
            continue

        # Determine destination
        folder = CATEGORY_SLUGS.get(category, "other")
        safe_topic = re.sub(r'[^a-zA-Z0-9_\-\s]', '', topic).replace(' ', '_')[:80]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        dest_path = f"{folder}/{timestamp}-{safe_topic}-{submission_id[-4:]}.md"

        # Move file
        success = move_file(filepath, dest_path, content)
        if success:
            moved += 1
            # Store filename in Supabase
            try:
                supabase.table("submissions").update({
                    "pending_filename": dest_path,
                    "status": "approved"
                }).eq("submission_id", submission_id).execute()
            except Exception:
                pass
        else:
            failed += 1

    # Summary
    print(f"\n[3/3] COMPLETE")
    print("=" * 60)
    print(f"Total files: {total}")
    print(f"Moved to category folders: {moved}")
    print(f"Flagged (stays in pending): {flagged}")
    print(f"Failed: {failed}")
    print(f"Skipped (no ID): {skipped}")
    print("=" * 60)
    sys.stdout.flush()


if __name__ == "__main__":
    organize_all()
