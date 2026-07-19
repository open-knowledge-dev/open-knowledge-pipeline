"""
Ghana-GPT Batch Organizer — Security Scan + Category Move
===========================================================
Processes pending files in batches with rate limiting.
Runs for 50 minutes per hour, then stops. Resumes next run.
Handles 6M+ files over multiple weeks.
"""

import os
import sys
import re
import base64
import time
import requests
from datetime import datetime, timezone

print("[INIT] Starting batch organizer...")
sys.stdout.flush()

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

# Rate limiting: max API calls per hour
MAX_CALLS_PER_HOUR = 4000
# Safety margin — stop 5 minutes before the hour ends
MAX_RUNTIME_SECONDS = 3300  # 55 minutes


def security_scan(content: str) -> list:
    findings = []
    for name, pattern in CRITICAL_PATTERNS.items():
        if pattern.search(content):
            findings.append(name)
    return findings


def list_page(page: int):
    url = f"{GITHUB_API}/repos/{GITHUB_KNOWLEDGE_REPO}/contents/pending"
    params = {"page": page, "per_page": 100}
    response = requests.get(url, headers=GITHUB_HEADERS, params=params, timeout=30)
    if response.status_code == 200:
        data = response.json()
        return [item for item in data if item["name"].endswith(".md")]
    return []


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
        sha = get_file_sha(source_path)
        if sha:
            delete_url = f"{GITHUB_API}/repos/{GITHUB_KNOWLEDGE_REPO}/contents/{source_path}"
            delete_payload = {"message": f"Batch remove: {source_path}", "sha": sha, "branch": "main"}
            requests.delete(delete_url, json=delete_payload, headers=GITHUB_HEADERS, timeout=15)
        return True
    except Exception:
        return False


def extract_category(content: str) -> str:
    match = re.search(r'\*\*Category:\*\*\s*(.+)', content)
    return match.group(1).strip() if match else "Other"


def extract_submission_id(content: str) -> str:
    match = re.search(r'GHGPT-\d{4}-\d{4}', content)
    return match.group(0) if match else ""


def extract_topic(content: str) -> str:
    match = re.search(r'^#\s+(.+)', content, re.MULTILINE)
    return match.group(1).strip()[:80] if match else "untitled"


def organize_batch():
    print("=" * 60)
    print("Batch Organizer — Weekly Rate-Limited Mode")
    print("=" * 60)
    print(f"Max runtime: {MAX_RUNTIME_SECONDS}s ({MAX_RUNTIME_SECONDS//60} min)")
    print(f"Max API calls: {MAX_CALLS_PER_HOUR}")
    sys.stdout.flush()

    # Load progress
    start_page = 1
    try:
        with open("batch_progress.txt", "r") as f:
            start_page = int(f.read().strip())
        print(f"Resuming from page {start_page}")
    except FileNotFoundError:
        print("Starting from page 1")

    start_time = time.time()
    api_calls = 0
    moved = 0
    flagged = 0
    failed = 0

    page = start_page
    while True:
        # Check time limit
        elapsed = time.time() - start_time
        if elapsed > MAX_RUNTIME_SECONDS:
            print(f"\nTime limit reached ({elapsed:.0f}s). Saving progress to page {page}.")
            with open("batch_progress.txt", "w") as f:
                f.write(str(page))
            break

        # Check API limit
        if api_calls >= MAX_CALLS_PER_HOUR:
            print(f"\nAPI limit reached ({api_calls} calls). Saving progress to page {page}.")
            with open("batch_progress.txt", "w") as f:
                f.write(str(page))
            break

        # Get page of files
        files = list_page(page)
        api_calls += 1

        if not files:
            print(f"\nNo more files at page {page}. Done!")
            break

        for item in files:
            if api_calls >= MAX_CALLS_PER_HOUR or (time.time() - start_time) > MAX_RUNTIME_SECONDS:
                break

            filepath = item["path"]
            content = get_file_content(filepath)
            api_calls += 1

            if not content:
                failed += 1
                continue

            # Security scan
            findings = security_scan(content)
            if findings:
                flagged += 1
                continue

            category = extract_category(content)
            submission_id = extract_submission_id(content)
            topic = extract_topic(content)

            if not submission_id:
                failed += 1
                continue

            folder = CATEGORY_SLUGS.get(category, "other")
            safe_topic = re.sub(r'[^a-zA-Z0-9_\-\s]', '', topic).replace(' ', '_')[:80]
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            dest_path = f"{folder}/{timestamp}-{safe_topic}-{submission_id[-4:]}.md"

            success = move_file(filepath, dest_path, content)
            api_calls += 2

            if success:
                moved += 1
                try:
                    supabase.table("submissions").update({
                        "pending_filename": dest_path,
                        "status": "approved"
                    }).eq("submission_id", submission_id).execute()
                    api_calls += 1
                except Exception:
                    pass
            else:
                failed += 1

            time.sleep(0.1)

        print(f"Page {page}: {moved} moved, {flagged} flagged, {failed} failed")
        sys.stdout.flush()
        page += 1

    print(f"\nSession complete: {moved} moved, {flagged} flagged, {failed} failed")
    print(f"API calls: {api_calls}")
    print(f"Resume from page {page} next run")
    sys.stdout.flush()


if __name__ == "__main__":
    organize_batch()
