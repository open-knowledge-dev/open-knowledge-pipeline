"""
Scraper Metadata Logger — v2.0
================================
Helper module for scrapers to log source/model metadata to 
entry-metadata.jsonl in the private knowledge repo.

This is called AFTER a successful submission to the training form,
so we have a valid submission_id to log.

ALLOWED SOURCES:
- cloudflare: @cf/qwen/qwen3-30b-a3b-fp8, @cf/mistral/mistral-7b-instruct-v0.2-lora
- mistral: mistral-small-latest
- human: human contributions (email required)
- web: web scrapers
- public_domain: public domain books

BANNED:
- All Llama models (Meta) — never use, never log

Usage:
    from scraper_metadata import log_entry_metadata
    
    success = log_entry_metadata(
        submission_id="XXXX-YYYY",
        source="cloudflare",
        model="@cf/qwen/qwen3-30b-a3b-fp8",
        type="ai",
        category="Agriculture & Farming",
        email=""
    )

Environment variables needed:
    - GH_TOKEN: GitHub API token
    - KNOWLEDGE_REPO: "org/repo-name"
"""

import os
import json
import base64
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import time


# ===========================================================================
# Configuration
# ===========================================================================

GITHUB_API = "https://api.github.com"
METADATA_FILE_PATH = "admin/entry-metadata.jsonl"

# Retry settings
RETRY_COUNT = 3
RETRY_DELAY = 2
REQUEST_TIMEOUT = 15

# Allowed sources
ALLOWED_SOURCES = ["cloudflare", "mistral", "human", "web", "public_domain"]

# Allowed types
ALLOWED_TYPES = ["ai", "human", "web", "public_domain"]

# Clean models (Apache 2.0 or permissive)
CLEAN_MODELS = [
    "@cf/qwen/qwen3-30b-a3b-fp8",
    "@cf/mistral/mistral-7b-instruct-v0.2-lora",
    "@cf/qwen/qwq-32b",
    "@cf/qwen/qwen3.8-27b",
    "mistral-small-latest",
    "mistral-medium-latest",
]


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
                    print(f"  [Metadata] GitHub rate limit. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                return response
            
            if response.status_code >= 500:
                print(f"  [Metadata] GitHub server error {response.status_code}. Retry {attempt + 1}/{RETRY_COUNT}...")
                time.sleep(RETRY_DELAY * (attempt + 1))
                continue
            
            return response
            
        except requests.exceptions.RequestException as e:
            print(f"  [Metadata] Request error: {e}. Retry {attempt + 1}/{RETRY_COUNT}...")
            time.sleep(RETRY_DELAY * (attempt + 1))
    
    return None


def _get_file_content(path: str) -> Optional[tuple]:
    """
    Get file content and SHA from GitHub.
    Returns (content_string, sha) or (None, None) if file doesn't exist.
    """
    repo = _get_repo()
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    
    response = _github_request("GET", url)
    if response is None:
        return None, None
    
    if response.status_code == 404:
        return "", None
    
    if response.status_code != 200:
        print(f"  [Metadata] Failed to read {path}: {response.status_code}")
        return None, None
    
    data = response.json()
    content_b64 = data.get("content", "")
    sha = data.get("sha", "")
    
    if not content_b64:
        return "", sha
    
    try:
        content = base64.b64decode(content_b64).decode("utf-8")
        return content, sha
    except Exception as e:
        print(f"  [Metadata] Failed to decode {path}: {e}")
        return None, None


def _write_file_content(path: str, content: str, sha: str = "", message: str = "") -> bool:
    """Write content back to GitHub."""
    repo = _get_repo()
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    
    payload = {
        "message": message or "Update entry-metadata.jsonl",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }
    
    if sha:
        payload["sha"] = sha
    
    response = _github_request("PUT", url, json=payload)
    if response is None:
        return False
    
    if response.status_code in [200, 201]:
        return True
    
    print(f"  [Metadata] Failed to write {path}: {response.status_code}")
    return False


# ===========================================================================
# Main Logger Function
# ===========================================================================

def log_entry_metadata(
    submission_id: str,
    source: str,
    model: str,
    type: str,
    category: str,
    email: str = "",
    date: Optional[str] = None,
) -> bool:
    """
    Log metadata for a single submission entry.
    
    Args:
        submission_id: Required, the submission ID
        source: cloudflare, mistral, human, web, public_domain
        model: Specific clean model name if AI-generated, empty string for human/web
        type: ai, human, web, public_domain
        category: Category name from the submission
        email: Contributor email if human, empty for scrapers
        date: ISO timestamp, defaults to now
    
    Returns:
        True if successful, False otherwise
    
    Example:
        log_entry_metadata(
            submission_id="XXXX-YYYY",
            source="cloudflare",
            model="@cf/qwen/qwen3-30b-a3b-fp8",
            type="ai",
            category="Agriculture & Farming"
        )
    """
    # Validate required fields
    if not submission_id:
        print("[Metadata] ERROR: submission_id is required")
        return False
    
    if not source:
        print("[Metadata] ERROR: source is required")
        return False
    
    if not type:
        print("[Metadata] ERROR: type is required")
        return False
    
    # Validate source
    if source not in ALLOWED_SOURCES:
        print(f"[Metadata] ERROR: source must be one of {ALLOWED_SOURCES}")
        return False
    
    # Validate type
    if type not in ALLOWED_TYPES:
        print(f"[Metadata] ERROR: type must be one of {ALLOWED_TYPES}")
        return False
    
    # If AI type, model must be provided and must be a clean model
    if type == "ai":
        if not model:
            print("[Metadata] ERROR: model is required for AI-generated content")
            return False
        if model not in CLEAN_MODELS:
            print(f"[Metadata] WARNING: model '{model}' not in clean models list")
    
    # Build metadata entry
    entry = {
        "submission_id": submission_id,
        "source": source,
        "model": model or "",
        "type": type,
        "date": date or datetime.now(timezone.utc).isoformat(),
        "category": category or "",
        "email": email or "",
    }
    
    # Read current file
    content, sha = _get_file_content(METADATA_FILE_PATH)
    
    if content is None:
        print("[Metadata] ERROR: Could not read existing metadata file")
        return False
    
    # Append new line
    new_line = json.dumps(entry) + "\n"
    updated_content = content + new_line
    
    # Write back
    message = f"Log metadata: {submission_id}"
    success = _write_file_content(METADATA_FILE_PATH, updated_content, sha, message)
    
    if success:
        print(f"[Metadata] ✅ Logged: {submission_id} | {source} | {model}")
    else:
        print(f"[Metadata] ❌ Failed to log: {submission_id}")
    
    return success


# ===========================================================================
# Convenience Functions for Different Sources
# ===========================================================================

def log_ai_entry(
    submission_id: str, 
    source: str, 
    model: str, 
    category: str
) -> bool:
    """Log an AI-generated entry."""
    return log_entry_metadata(
        submission_id=submission_id,
        source=source,
        model=model,
        type="ai",
        category=category,
    )


def log_human_entry(
    submission_id: str, 
    email: str, 
    category: str
) -> bool:
    """Log a human-contributed entry."""
    return log_entry_metadata(
        submission_id=submission_id,
        source="human",
        model="",
        type="human",
        category=category,
        email=email,
    )


def log_web_entry(
    submission_id: str, 
    source: str, 
    category: str
) -> bool:
    """Log a web-scraped entry."""
    return log_entry_metadata(
        submission_id=submission_id,
        source=source,
        model="",
        type="web",
        category=category,
    )


def log_public_domain_entry(
    submission_id: str, 
    source: str, 
    category: str
) -> bool:
    """Log a public domain book entry."""
    return log_entry_metadata(
        submission_id=submission_id,
        source=source,
        model="",
        type="public_domain",
        category=category,
    )


# ===========================================================================
# Validation & Utilities
# ===========================================================================

def validate_metadata_file() -> bool:
    """Check if entry-metadata.jsonl exists and is valid JSONL."""
    content, sha = _get_file_content(METADATA_FILE_PATH)
    
    if content is None:
        print("[Metadata] ❌ Could not read entry-metadata.jsonl")
        return False
    
    if content == "":
        print("[Metadata] ✅ entry-metadata.jsonl exists and is empty")
        return True
    
    # Validate each line is valid JSON
    lines = content.strip().split("\n")
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as e:
            print(f"[Metadata] ❌ Line {i} is invalid JSON: {e}")
            return False
    
    print(f"[Metadata] ✅ entry-metadata.jsonl has {len(lines)} valid entries")
    return True


def get_metadata_count() -> int:
    """Get the number of entries in entry-metadata.jsonl."""
    content, sha = _get_file_content(METADATA_FILE_PATH)
    if content is None:
        return 0
    
    lines = [l for l in content.strip().split("\n") if l.strip()]
    return len(lines)


def get_metadata_by_submission_id(submission_id: str) -> Optional[Dict[str, Any]]:
    """Get metadata for a specific submission ID."""
    content, sha = _get_file_content(METADATA_FILE_PATH)
    if content is None:
        return None
    
    for line in content.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if data.get("submission_id") == submission_id:
                return data
        except json.JSONDecodeError:
            continue
    
    return None


if __name__ == "__main__":
    # Self-test when run directly
    print("=" * 60)
    print("Scraper Metadata Logger — Self-Test")
    print("=" * 60)
    
    if not os.getenv("GH_TOKEN") or not os.getenv("KNOWLEDGE_REPO"):
        print("❌ GH_TOKEN and KNOWLEDGE_REPO must be set")
        print("   Run: GH_TOKEN=xxx KNOWLEDGE_REPO=xxx python scraper_metadata.py")
        print("=" * 60)
        exit(1)
    
    print(f"Repo: {os.getenv('KNOWLEDGE_REPO')}")
    print(f"File: {METADATA_FILE_PATH}")
    
    # Validate the file exists
    content, sha = _get_file_content(METADATA_FILE_PATH)
    if content is None:
        print("❌ Could not read entry-metadata.jsonl")
        print("   Please create this file first in the knowledge repo")
        print("   Path: admin/entry-metadata.jsonl")
        print("=" * 60)
        exit(1)
    
    print(f"✅ File exists with {len(content)} characters")
    
    # Count entries
    count = get_metadata_count()
    print(f"✅ {count} entries currently logged")
    
    print("=" * 60)
    print("Self-test passed.")
    print("=" * 60)
