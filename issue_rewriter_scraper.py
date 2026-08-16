#!/usr/bin/env python3
"""
Issue Rewriter Scraper — v1.0
==============================
Picks tainted files from ghana-gpt-knowledge/issues/
Rewrites content (removes banned orgs)
Submits to training form as new knowledge
Deletes the original file after successful submission
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
TRAINING_FORM_URL = os.getenv("TRAINING_FORM_URL", "")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")

GITHUB_API = "https://api.github.com"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

REQUEST_TIMEOUT = 90
SUBMISSION_DELAY = 30

CI_MODE = os.getenv("CI", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
MAX_FILES = int(os.getenv("MAX_FILES", "5")) if os.getenv("MAX_FILES") else 5

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

BANNED_ORGS_STRING = ", ".join(BANNED_ORGS)
BANNED_TERMS_STRING = ", ".join(BANNED_TERMS)

REWRITE_PROMPT = (
    f"You are an African knowledge expert. Rewrite the following content to "
    f"REMOVE ALL references to international organizations and external entities.\n\n"
    f"DO NOT mention: {BANNED_ORGS_STRING}\n"
    f"DO NOT mention: {BANNED_TERMS_STRING}\n\n"
    f"Rules:\n"
    f"1. Remove every mention of the above organizations and terms\n"
    f"2. Replace 'according to WHO' → 'according to local experts'\n"
    f"3. Replace 'UN program' → 'community program'\n"
    f"4. Replace 'World Bank' → 'regional initiative'\n"
    f"5. Remove 'funding', 'grant', 'NGO' entirely\n"
    f"6. Present all information as African knowledge from local communities\n"
    f"7. Keep all factual information intact\n"
    f"8. Write in plain text. No markdown.\n"
    f"9. At least 400 words.\n"
    f"10. IMPORTANT: Check your work. If you see ANY banned term, remove it."
)

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
    except Exception:
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
    except Exception:
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
    except Exception:
        return False


# ===========================================================================
# Content Detection
# ===========================================================================

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
# AI Rewriting
# ===========================================================================

def rewrite_with_groq(content: str, attempt: int = 0) -> Optional[str]:
    if not GROQ_API_KEY:
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

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.4,
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
    if not MISTRAL_API_KEY:
        return None

    extra = ""
    if attempt > 0:
        extra = f"\n\nPREVIOUS ATTEMPT FAILED. Rewrite AGAIN. Remove ALL references to: {BANNED_ORGS_STRING}."

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
    max_retries = 3
    current_content = content

    for attempt in range(max_retries):
        rewritten = None

        if GROQ_API_KEY:
            rewritten = rewrite_with_groq(current_content, attempt)
        elif MISTRAL_API_KEY:
            rewritten = rewrite_with_mistral(current_content, attempt)

        if not rewritten:
            continue

        # Clean markdown
        rewritten = re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'\1', rewritten)
        rewritten = re.sub(r'^#{1,6}\s+', '', rewritten, flags=re.MULTILINE)
        rewritten = re.sub(r'```[^`]*```', '', rewritten)
        rewritten = rewritten.strip()

        has_banned, found = detect_banned_content(rewritten)
        if not has_banned:
            return rewritten

        print(f"    ⚠️ Attempt {attempt + 1} still has: {', '.join(found[:3])}")
        current_content = rewritten

    return None


# ===========================================================================
# Submission to Training Form
# ===========================================================================

def submit_to_form(topic: str, category: str, knowledge: str, language: str = "English") -> Tuple[bool, str]:
    session = requests.Session()
    try:
        form_response = session.get(TRAINING_FORM_URL, timeout=REQUEST_TIMEOUT)
        if form_response.status_code != 200:
            return False, ""
        html = form_response.text

        csrf_match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        if not csrf_match:
            return False, ""
        csrf_token = csrf_match.group(1)

        code_match = re.search(r'verification-code[^>]*>(\d{6})<', html)
        if not code_match:
            return False, ""
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
        return False, ""
    except Exception as e:
        print(f"  Submission error: {e}")
        return False, ""


# ===========================================================================
# Main
# ===========================================================================

def process_issue_file(file_path: str, dry_run: bool = True) -> Dict:
    """Process a single issue file: rewrite, submit, delete."""
    result = {
        "file": file_path,
        "status": "unknown",
        "submission_id": None,
        "error": None
    }

    print(f"\n  Processing: {file_path}")

    # Get content
    content = get_file_content(file_path)
    if not content:
        result["status"] = "error"
        result["error"] = "Could not read file"
        return result

    # Extract original category from path or content
    # Try to guess from filename or content
    category = "Other"
    # Look for category in filename
    for cat in ["agriculture", "business", "culture", "education", "health",
                "technology", "tourism", "history", "food", "music",
                "language", "religion", "sports", "fashion", "environment",
                "governance", "family", "arts", "science"]:
        if cat in file_path.lower():
            category = cat.title().replace("_", " & ")
            break

    # Extract topic from filename
    filename = file_path.split("/")[-1]
    # Remove date and ID from filename
    topic_parts = filename.replace(".md", "").split("-")
    # Skip date parts (first 2-3 parts)
    topic_parts = [p for p in topic_parts if not re.match(r'^\d{8}$', p) and not re.match(r'^\d{4}$', p)]
    topic = " ".join(topic_parts).replace("_", " ").title()
    if not topic or len(topic) < 5:
        topic = "Knowledge from Community Sources"

    print(f"    Topic: {topic[:60]}...")
    print(f"    Category: {category}")

    if dry_run:
        print(f"    [DRY RUN] Would rewrite and submit")
        result["status"] = "dry_run"
        return result

    # Rewrite
    rewritten = rewrite_content(content)
    if not rewritten:
        result["status"] = "error"
        result["error"] = "Failed to rewrite after 3 attempts"
        return result

    # Check length
    if len(rewritten.split()) < 300:
        result["status"] = "error"
        result["error"] = "Rewritten content too short"
        return result

    # Submit to training form
    success, submission_id = submit_to_form(topic, category, rewritten, "English")

    if not success:
        result["status"] = "error"
        result["error"] = "Submission failed"
        return result

    result["submission_id"] = submission_id
    print(f"    ✅ Submitted! ID: {submission_id}")

    # Delete the original file from issues/
    if delete_file(file_path, f"Rewritten and submitted: {submission_id}"):
        result["status"] = "completed"
        print(f"    ✅ Original file deleted")
    else:
        result["status"] = "submitted_but_not_deleted"
        result["error"] = "File not deleted after submission"

    return result


def main():
    print("=" * 70)
    print("Issue Rewriter Scraper v1.0")
    print("=" * 70)
    print(f"Repo: {KNOWLEDGE_REPO}")
    print(f"DRY RUN: {DRY_RUN}")
    print(f"Max files: {MAX_FILES}")
    print(f"Groq: {'ACTIVE' if GROQ_API_KEY else 'NOT SET'}")
    print("=" * 70)

    if not GH_TOKEN or not KNOWLEDGE_REPO:
        print("ERROR: GitHub credentials not configured")
        sys.exit(1)

    if not GROQ_API_KEY and not MISTRAL_API_KEY:
        print("ERROR: No AI API keys configured")
        sys.exit(1)

    # Get all files in issues/
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
        "dry_run": 0,
        "details": []
    }

    for i, file_info in enumerate(md_files[:MAX_FILES]):
        file_path = file_info["path"]
        result = process_issue_file(file_path, DRY_RUN)
        results["processed"] += 1

        if result["status"] == "dry_run":
            results["dry_run"] += 1
        elif result["status"] == "completed":
            results["completed"] += 1
        else:
            results["failed"] += 1

        results["details"].append(result)

        if i < len(md_files[:MAX_FILES]) - 1:
            print(f"  Waiting {SUBMISSION_DELAY}s...")
            time.sleep(SUBMISSION_DELAY)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Files processed: {results['processed']}")
    print(f"Completed (rewritten + submitted + deleted): {results['completed']}")
    print(f"Failed: {results['failed']}")
    print(f"Dry run: {results['dry_run']}")

    if results["details"]:
        print("\nDetails:")
        for r in results["details"]:
            status = r["status"]
            if status == "completed":
                print(f"  ✅ {r['file']} → {r.get('submission_id', 'unknown')}")
            elif status == "dry_run":
                print(f"  🔄 {r['file']} [DRY RUN]")
            else:
                print(f"  ❌ {r['file']} — {r.get('error', 'unknown')}")

    print("=" * 70)


if __name__ == "__main__":
    main()
