#!/usr/bin/env python3
"""
Issue Rewriter — v3.2
======================
Picks files from issues/ in the private repo.
Rewrites content using Cloudflare Workers AI (removes banned orgs).
Uses AGGRESSIVE rewrite prompt to delete banned content.
FIXED: Case-sensitive detection for short terms (WHO, UN, EU).
Submits to training form as new knowledge.
Deletes the original file after successful submission.
Runs daily — 27 files per run.
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

CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_MODEL = os.getenv("CLOUDFLARE_MODEL", "@cf/meta/llama-3.1-8b-instruct")

GH_TOKEN = os.getenv("GH_TOKEN", "")
KNOWLEDGE_REPO = os.getenv("KNOWLEDGE_REPO", "")
TRAINING_FORM_URL = os.getenv("TRAINING_FORM_URL", "")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")

GITHUB_API = "https://api.github.com"
CLOUDFLARE_API_URL = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{CLOUDFLARE_MODEL}" if CLOUDFLARE_ACCOUNT_ID else ""

REQUEST_TIMEOUT = 120
RETRY_COUNT = 3
RETRY_DELAY = 2

MAX_FILES = int(os.getenv("MAX_FILES", "27"))

# ===========================================================================
# Banned Organizations — Case-sensitive for short terms
# ===========================================================================

BANNED_ORGS = [
    "FAO",
    "Food and Agriculture Organization",
    "World Health Organization",
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

# Short terms that must be EXACT matches and case-sensitive
SHORT_TERMS = {
    "WHO": "WHO",
    "UN": "UN",
    "EU": "EU",
}

BANNED_TERMS = [
    "development program", "aid program", "international assistance",
    "foreign aid", "development agency", "grant", "funding", "NGO",
    "non-governmental", "donor", "beneficiary", "recipient"
]

BANNED_ORGS_STRING = ", ".join(BANNED_ORGS)
BANNED_TERMS_STRING = ", ".join(BANNED_TERMS)


def build_banned_patterns() -> List[re.Pattern]:
    patterns = []

    # Full organization names — case-insensitive
    for term in BANNED_ORGS:
        if len(term) > 3:
            patterns.append(re.compile(rf'{re.escape(term)}', re.IGNORECASE))

    # Short terms — case-sensitive with word boundaries
    for term, pattern in SHORT_TERMS.items():
        patterns.append(re.compile(rf'\b{re.escape(pattern)}\b'))

    # Banned terms — case-insensitive
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
                    print(f"    GitHub rate limit. Waiting {wait_time}s...")
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


def delete_file(path: str, message: str) -> Tuple[bool, str]:
    sha = get_file_sha(path)
    if not sha:
        return False, "Could not get file SHA"

    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    payload = {
        "message": message,
        "sha": sha,
        "branch": "main",
    }
    response = api_request("DELETE", url, json=payload)
    if response and response.status_code == 200:
        return True, "Deleted successfully"
    return False, f"Delete failed: {response.status_code if response else 'No response'}"


# ===========================================================================
# Cloudflare AI Rewriting — AGGRESSIVE
# ===========================================================================

REWRITE_PROMPT = (
    f"You are an African knowledge expert. Rewrite the following content.\n\n"
    f"STRICT RULES:\n"
    f"1. DELETE any sentence that mentions these organizations: {BANNED_ORGS_STRING}\n"
    f"2. DELETE any sentence that mentions: {BANNED_TERMS_STRING}\n"
    f"3. Do NOT replace them — DELETE them entirely\n"
    f"4. If a paragraph has 3 or more banned terms, delete the whole paragraph\n"
    f"5. Rewrite the remaining content to flow naturally\n"
    f"6. Add African cultural context and local knowledge\n"
    f"7. Write at least 400 words\n"
    f"8. Plain text only — no markdown\n"
    f"9. IMPORTANT: After writing, check your work. If you see ANY banned term, you have failed."
)


def rewrite_with_cloudflare(content: str, attempt: int = 0) -> Optional[str]:
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
        return None

    extra = ""
    if attempt > 0:
        extra = f"\n\nPREVIOUS ATTEMPT FAILED. You still included banned terms. DELETE them. Do NOT keep any sentence with banned terms."

    system_prompt = REWRITE_PROMPT + extra

    if len(content) > 8000:
        content = content[:8000]

    user_prompt = f"Rewrite this content. DELETE all banned organizations and terms:\n\n{content}"

    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 4500,
        "temperature": 0.3,
    }

    try:
        response = requests.post(CLOUDFLARE_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                return data.get("result", {}).get("response", "")
            else:
                print(f"    Cloudflare API error: {data.get('errors', 'Unknown error')}")
                return None
        elif response.status_code == 429:
            wait_time = (attempt + 1) * 30
            print(f"    Cloudflare rate limit. Waiting {wait_time}s...")
            time.sleep(wait_time)
            return None
        else:
            print(f"    Cloudflare error: {response.status_code}")
            return None
    except Exception as e:
        print(f"    Cloudflare exception: {e}")
        return None


def rewrite_content(content: str) -> Tuple[Optional[str], str]:
    max_retries = 4
    current_content = content

    for attempt in range(max_retries):
        rewritten = rewrite_with_cloudflare(current_content, attempt)

        if not rewritten:
            continue

        rewritten = re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'\1', rewritten)
        rewritten = re.sub(r'^#{1,6}\s+', '', rewritten, flags=re.MULTILINE)
        rewritten = re.sub(r'```[^`]*```', '', rewritten)
        rewritten = rewritten.strip()

        has_banned, found = detect_banned_content(rewritten)
        if not has_banned:
            return rewritten, ""

        print(f"    ⚠️ Attempt {attempt + 1} still has: {', '.join(found[:3])}")
        current_content = rewritten

    return None, f"Failed to remove banned content after {max_retries} attempts"


# ===========================================================================
# Submission to Training Form
# ===========================================================================

def submit_to_form(topic: str, category: str, knowledge: str, language: str = "English") -> Tuple[bool, str]:
    session = requests.Session()
    try:
        form_response = session.get(TRAINING_FORM_URL, timeout=REQUEST_TIMEOUT)
        if form_response.status_code != 200:
            return False, f"Form returned {form_response.status_code}"

        html = form_response.text

        csrf_match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        if not csrf_match:
            return False, "Could not find CSRF token"

        csrf_token = csrf_match.group(1)

        code_match = re.search(r'verification-code[^>]*>(\d{6})<', html)
        if not code_match:
            return False, "Could not find verification code"

        verification_code = code_match.group(1)

        submit_data = {
            "topic": topic,
            "category": category,
            "knowledge": knowledge,
            "region": "",
            "language": language,
            "email": "",
            "verification_code": verification_code,
            "csrf_token": csrf_token,
            "app_check_token": SCRAPER_API_KEY,
            "copyright_confirm": "on",
        }

        submit_response = session.post(
            f"{TRAINING_FORM_URL}/submit",
            data=submit_data,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        if submit_response.status_code == 200:
            id_match = re.search(r'GHGPT-\d{4}-\d{4}', submit_response.text)
            submission_id = id_match.group(0) if id_match else "unknown"
            return True, submission_id

        return False, f"Submit failed: {submit_response.status_code}"

    except Exception as e:
        return False, f"Submission error: {e}"


# ===========================================================================
# Main Logic
# ===========================================================================

def extract_info_from_filename(filename: str) -> Tuple[str, str]:
    name = filename.replace(".md", "")
    parts = name.split("-")

    meaningful = []
    for p in parts:
        if re.match(r'^\d{8}$', p):
            continue
        if re.match(r'^\d{6}$', p):
            continue
        if re.match(r'^\d{4}$', p):
            continue
        meaningful.append(p)

    topic = " ".join(meaningful).replace("_", " ").title()
    if not topic or len(topic) < 5:
        topic = "Knowledge from Community Sources"

    category = "Other"
    category_map = {
        "agriculture": "Agriculture & Farming",
        "farming": "Agriculture & Farming",
        "business": "Business & Finance",
        "finance": "Business & Finance",
        "culture": "Culture & Traditions",
        "education": "Education & Learning",
        "learning": "Education & Learning",
        "health": "Health & Medicine",
        "medicine": "Health & Medicine",
        "tech": "Technology & Innovation",
        "technology": "Technology & Innovation",
        "innovation": "Technology & Innovation",
        "tourism": "Tourism & Travel",
        "travel": "Tourism & Travel",
        "history": "History & Heritage",
        "heritage": "History & Heritage",
        "food": "Food & Cuisine",
        "cuisine": "Food & Cuisine",
        "music": "Music & Dance",
        "dance": "Music & Dance",
        "language": "Language & Proverbs",
        "religion": "Religion & Spirituality",
        "sports": "Sports & Games",
        "fashion": "Fashion & Textiles",
        "environment": "Environment & Nature",
        "governance": "Governance & Leadership",
        "leadership": "Governance & Leadership",
        "family": "Family & Relationships",
        "arts": "Arts & Crafts",
        "science": "Science & Innovation",
    }

    lower_name = name.lower()
    for key, value in category_map.items():
        if key in lower_name:
            category = value
            break

    return topic, category


def process_file(file_path: str) -> Dict:
    result = {
        "file": file_path,
        "status": "unknown",
        "submission_id": None,
        "error": None
    }

    print(f"\n  Processing: {file_path}")

    content = get_file_content(file_path)
    if not content:
        result["status"] = "error"
        result["error"] = "Could not read file"
        return result

    filename = file_path.split("/")[-1]
    topic, category = extract_info_from_filename(filename)

    print(f"    Topic: {topic[:60]}...")
    print(f"    Category: {category}")

    rewritten, error = rewrite_content(content)
    if not rewritten:
        result["status"] = "error"
        result["error"] = error
        return result

    if len(rewritten.split()) < 300:
        result["status"] = "error"
        result["error"] = f"Rewritten content too short: {len(rewritten.split())} words"
        return result

    success, msg = submit_to_form(topic, category, rewritten, "English")

    if not success:
        result["status"] = "error"
        result["error"] = msg
        return result

    result["submission_id"] = msg
    print(f"    ✅ Submitted! ID: {msg}")

    success, msg = delete_file(file_path, f"Rewritten and submitted: {msg}")
    if success:
        result["status"] = "completed"
        print(f"    ✅ Original file deleted")
    else:
        result["status"] = "submitted_but_not_deleted"
        result["error"] = msg
        print(f"    ⚠️ {msg}")

    return result


def main():
    print("=" * 70)
    print("Issue Rewriter v3.2 — Cloudflare AI (Fixed Detection)")
    print("=" * 70)
    print(f"Repo: {KNOWLEDGE_REPO}")
    print(f"Max files: {MAX_FILES}")
    print(f"Cloudflare: {'ACTIVE' if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN else 'NOT SET'}")
    print(f"Model: {CLOUDFLARE_MODEL}")
    print("=" * 70)

    missing = []
    if not GH_TOKEN:
        missing.append("GH_TOKEN")
    if not KNOWLEDGE_REPO:
        missing.append("KNOWLEDGE_REPO")
    if not TRAINING_FORM_URL:
        missing.append("TRAINING_FORM_URL")
    if not SCRAPER_API_KEY:
        missing.append("SCRAPER_API_KEY")
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
        missing.append("CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN")

    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    issues = get_repo_contents("issues")
    if not issues:
        print("No files in issues/ folder.")
        return

    md_files = [f for f in issues if f.get("name", "").endswith(".md")]

    if not md_files:
        print("No .md files in issues/ folder.")
        return

    print(f"\nFound {len(md_files)} files in issues/")
    print(f"Processing up to {MAX_FILES} files...")
    print("-" * 70)

    results = {
        "processed": 0,
        "completed": 0,
        "failed": 0,
        "errors": []
    }

    for i, file_info in enumerate(md_files[:MAX_FILES]):
        file_path = file_info["path"]
        result = process_file(file_path)
        results["processed"] += 1

        if result["status"] == "completed":
            results["completed"] += 1
        else:
            results["failed"] += 1
            results["errors"].append({
                "file": file_path,
                "error": result.get("error", "Unknown error")
            })

        if i < len(md_files[:MAX_FILES]) - 1:
            print(f"  Waiting 10s...")
            time.sleep(10)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Files processed: {results['processed']}")
    print(f"Completed (rewritten + submitted + deleted): {results['completed']}")
    print(f"Failed: {results['failed']}")

    if results["errors"]:
        print("\nErrors:")
        for error in results["errors"]:
            print(f"  ❌ {error['file']}: {error['error']}")

    print("=" * 70)

    if results["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
