"""
Cloudflare Workers AI Scraper — v5.0.0
=====================================
Uses Cloudflare Workers AI free tier to generate knowledge entries.
Submits through the training form — same pipeline as all other scrapers.

New in v5.0.0:
- Human voice validation via human_voice_checker
- Aggressive markdown stripping
- Retry logic (3 attempts) on validation failure
- Validation failures logged to admin/validation-failures.jsonl
- Sentences capped at 20 words
- No AI-sounding words

Rate limiting built in:
- MIN_DELAY 10s / MAX_DELAY 20s between entries
- Exponential backoff on 429: 30s → 60s → skip
- Random jitter 1-5s added to every delay
- Per-minute cap: 5 requests/minute

Models: Clean models only — NO Llama/Meta
- @cf/qwen/qwen3-30b-a3b-fp8 (Apache 2.0)
- @cf/mistral/mistral-7b-instruct-v0.2-lora (Apache 2.0)

Free tier: 10,000 requests/day
"""

import os
import sys
import re
import time
import random
import json
import base64
import requests
from datetime import datetime, timezone
from pathlib import Path

# Import human voice checker
try:
    from human_voice_checker import check_human_voice, strip_markdown_symbols
    VALIDATOR_AVAILABLE = True
except ImportError:
    # Try parent directory
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from human_voice_checker import check_human_voice, strip_markdown_symbols
        VALIDATOR_AVAILABLE = True
    except ImportError:
        VALIDATOR_AVAILABLE = False
        print("[WARNING] human_voice_checker.py not found. Validation disabled.")

# Import metadata logger
try:
    from scraper_metadata import log_entry_metadata
    METADATA_AVAILABLE = True
except ImportError:
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scraper_metadata import log_entry_metadata
        METADATA_AVAILABLE = True
    except ImportError:
        METADATA_AVAILABLE = False
        print("[WARNING] scraper_metadata.py not found. Metadata logging disabled.")


sys.path.insert(0, str(Path(__file__).parent))

from topics import TOPICS
from prompts import (
    get_system_prompt,
    get_user_prompt,
    get_banned_orgs_list,
    get_banned_instruction,
    USER_PROMPT_TEMPLATES,
)


# ===========================================================================
# Configuration
# ===========================================================================

ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")

# Default to clean Qwen model (Apache 2.0, training-safe)
MODEL = os.environ.get("CLOUDFLARE_MODEL", "@cf/qwen/qwen3-30b-a3b-fp8")
CATEGORY = os.environ.get("SCRAPER_CATEGORY", "Culture & Traditions")

TRAINING_FORM_URL = os.environ.get("TRAINING_FORM_URL", "")
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")
GH_TOKEN = os.environ.get("GH_TOKEN", "")
KNOWLEDGE_REPO = os.environ.get("KNOWLEDGE_REPO", "")

BASE_URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run"
GITHUB_API = "https://api.github.com"
VALIDATION_LOG_PATH = "admin/validation-failures.jsonl"

ENTRIES_PER_RUN = int(os.environ.get("ENTRIES_PER_RUN", "10"))
MIN_WORDS = int(os.environ.get("MIN_WORDS", "400"))
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "1500"))
TEMPERATURE = 0.75
MIN_DELAY = 10
MAX_DELAY = 20
REQUEST_TIMEOUT = 90
MAX_RETRIES = 3

# Rate limiting
MAX_REQUESTS_PER_MINUTE = 5
request_timestamps = []

# Prompt styles available
PROMPT_STYLES = list(USER_PROMPT_TEMPLATES.keys())


# ===========================================================================
# Validation Failure Logging
# ===========================================================================

def _github_headers() -> dict:
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GH_TOKEN:
        headers["Authorization"] = f"token {GH_TOKEN}"
    return headers


def log_validation_failure(topic: str, category: str, reason: str, details: dict, content: str) -> None:
    """Log a validation failure to the knowledge repo."""
    if not GH_TOKEN or not KNOWLEDGE_REPO:
        print(f"   [Validation] Cannot log failure (no GitHub credentials)")
        return

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scraper": "cloudflare_worker",
        "model": MODEL,
        "topic": topic,
        "category": category,
        "reason": reason,
        "details": details,
        "content_preview": content[:500] if content else "",
    }

    try:
        url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{VALIDATION_LOG_PATH}"

        # Get current content
        sha = ""
        current_content = ""
        try:
            resp = requests.get(url, headers=_github_headers(), timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                sha = data.get("sha", "")
                if data.get("content"):
                    current_content = base64.b64decode(data["content"]).decode("utf-8")
        except Exception:
            pass

        # Append new entry
        new_line = json.dumps(entry) + "\n"
        updated_content = current_content + new_line

        # Write back
        payload = {
            "message": f"Log validation failure: {topic[:50]}",
            "content": base64.b64encode(updated_content.encode("utf-8")).decode("utf-8"),
            "branch": "main",
        }
        if sha:
            payload["sha"] = sha

        requests.put(url, json=payload, headers=_github_headers(), timeout=15)
        print(f"   [Validation] Failure logged to {VALIDATION_LOG_PATH}")
    except Exception as e:
        print(f"   [Validation] Failed to log: {e}")


# ===========================================================================
# Rate Limiting
# ===========================================================================

def enforce_rate_limit():
    """Ensure no more than MAX_REQUESTS_PER_MINUTE requests are made."""
    global request_timestamps
    now = time.time()
    request_timestamps = [t for t in request_timestamps if now - t < 60]

    if len(request_timestamps) >= MAX_REQUESTS_PER_MINUTE:
        oldest = request_timestamps[0]
        wait_time = 60 - (now - oldest) + 2
        print(f"  Rate limit: {len(request_timestamps)} requests in last minute. Waiting {wait_time:.0f}s...")
        sys.stdout.flush()
        time.sleep(wait_time)
        request_timestamps = [t for t in request_timestamps if time.time() - t < 60]

    request_timestamps.append(time.time())


# ===========================================================================
# Content Generation
# ===========================================================================

def generate_entry(topic, system_prompt, user_prompt, model, retry_count=0):
    """Call Cloudflare Workers AI API with exponential backoff on 429."""
    enforce_rate_limit()

    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE
    }

    url = f"{BASE_URL}/{model}"

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)

        if response.status_code == 429:
            if retry_count == 0:
                wait_time = 30 + random.randint(1, 10)
                print(f"  429 rate limited. Waiting {wait_time}s (retry 1/3)...")
                sys.stdout.flush()
                time.sleep(wait_time)
                return generate_entry(topic, system_prompt, user_prompt, model, retry_count + 1)
            elif retry_count == 1:
                wait_time = 60 + random.randint(1, 15)
                print(f"  429 rate limited again. Waiting {wait_time}s (retry 2/3)...")
                sys.stdout.flush()
                time.sleep(wait_time)
                return generate_entry(topic, system_prompt, user_prompt, model, retry_count + 1)
            else:
                print(f"  429 third time — skipping this entry")
                return None

        response.raise_for_status()
        data = response.json()

        if data.get("success") and "result" in data:
            text = data["result"]["response"]
            if text is None:
                print(f"  API returned null response")
                return None
            return text.strip()
        else:
            errors = data.get("errors", [])
            print(f"  API error: {errors}")
            return None

    except requests.exceptions.Timeout:
        print(f"  Request timed out")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  Request failed: {e}")
        return None


# ===========================================================================
# Content Cleaning
# ===========================================================================

def clean_content(text):
    """
    Clean generated text — remove common AI artifacts.
    Uses human_voice_checker if available, otherwise basic cleaning.
    """
    if not text:
        return ""

    # Remove common AI opening lines
    prefixes = [
        "here is a detailed", "here is an article", "here's a comprehensive",
        "here's an overview", "certainly!", "of course!", "below is a",
        "the following is a", "here is a", "here's a",
    ]
    text_lower = text.lower()
    for prefix in prefixes:
        if text_lower.startswith(prefix):
            first_break = text.find("\n\n")
            if first_break > 0:
                text = text[first_break:].strip()
            break

    # Remove AI self-references
    text = re.sub(
        r'(?i)(as an AI|as a language model|I am an AI|based on my training|I cannot|I don\'t have personal)',
        '', text
    ).strip()

    # Aggressive markdown stripping
    if VALIDATOR_AVAILABLE:
        text = strip_markdown_symbols(text)
    else:
        # Fallback: basic markdown stripping
        text = re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'\1', text)
        text = re.sub(r'_{1,3}([^_]+?)_{1,3}', r'\1', text)
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^[\-\*\+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'```[^`]*```', '', text)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        text = re.sub(r'~~([^~]+?)~~', r'\1', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\|', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


# ===========================================================================
# Submission
# ===========================================================================

def submit_to_form(topic, category, knowledge, language="English"):
    """Submit knowledge to the training form."""
    session = requests.Session()
    try:
        print(f"    Fetching form...")
        form_response = session.get(TRAINING_FORM_URL, timeout=30)
        if form_response.status_code != 200:
            print(f"    Form returned {form_response.status_code}")
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

        print(f"    Submitting...")
        submit_response = session.post(
            f"{TRAINING_FORM_URL}/submit",
            data=submit_data,
            timeout=30,
            allow_redirects=True,
        )

        if submit_response.status_code == 200:
            id_match = re.search(r'GHGPT-\d{4}-\d{4}', submit_response.text)
            submission_id = id_match.group(0) if id_match else "unknown"
            print(f"    Submitted! ID: {submission_id}")
            return True, submission_id
        else:
            print(f"    Failed. Status: {submit_response.status_code}")
            return False, ""
    except Exception as e:
        print(f"    ERROR: {e}")
        return False, ""


# ===========================================================================
# Main Loop
# ===========================================================================

def run():
    """Main scraper loop."""
    print("=" * 60)
    print("Cloudflare Workers AI Scraper v5.0.0")
    print("=" * 60)
    print(f"Model: {MODEL}")
    print(f"Category: {CATEGORY}")
    print(f"Entries per run: {ENTRIES_PER_RUN}")
    print(f"Topic pool: {len(TOPICS)} topics")
    print(f"Prompt styles: {len(PROMPT_STYLES)} templates")
    print(f"Submitting to: {TRAINING_FORM_URL}")
    print(f"Rate limit: {MAX_REQUESTS_PER_MINUTE} requests/minute")
    print(f"Backoff: 30s → 60s → skip on 429")
    print(f"Banned orgs: {len(get_banned_orgs_list())} organizations blocked")
    print(f"Metadata: {'ENABLED' if METADATA_AVAILABLE else 'DISABLED'}")
    print(f"Human voice check: {'ENABLED' if VALIDATOR_AVAILABLE else 'DISABLED'}")
    print(f"Max retries per entry: {MAX_RETRIES}")
    print("-" * 60)
    sys.stdout.flush()

    if not ACCOUNT_ID or not API_TOKEN:
        print("ERROR: Missing CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_API_TOKEN")
        sys.exit(1)

    if not TRAINING_FORM_URL:
        print("ERROR: Missing TRAINING_FORM_URL")
        sys.exit(1)

    shuffled_topics = TOPICS.copy()
    random.shuffle(shuffled_topics)

    successful = 0
    failed = 0
    validation_rejected = 0

    for i, topic in enumerate(shuffled_topics[:ENTRIES_PER_RUN], 1):
        style = random.choice(PROMPT_STYLES)
        system_prompt = get_system_prompt(CATEGORY)
        user_prompt = get_user_prompt(topic, style)

        print(f"\n[{i}/{ENTRIES_PER_RUN}] {topic[:80]}...")
        print(f"   Model: {MODEL} | Style: {style}")
        sys.stdout.flush()

        # Try up to MAX_RETRIES times
        content = None
        validation_passed = False
        last_validation_details = {}

        for attempt in range(MAX_RETRIES):
            raw = generate_entry(topic, system_prompt, user_prompt, MODEL)

            if not raw:
                continue

            cleaned = clean_content(raw)

            if not VALIDATOR_AVAILABLE:
                # No validator — accept as-is
                content = cleaned
                validation_passed = True
                break

            # Validate
            passed, details = check_human_voice(cleaned)

            if passed:
                content = cleaned
                validation_passed = True
                break
            else:
                last_validation_details = details
                print(f"   Attempt {attempt + 1} failed validation: {details['reasons']}")
                sys.stdout.flush()
                # Small delay before retry
                time.sleep(5)

        # After retries, decide
        if not content:
            failed += 1
            print(f"   No response from API after {MAX_RETRIES} attempts")
        elif not validation_passed:
            validation_rejected += 1
            print(f"   Rejected after {MAX_RETRIES} validation attempts")
            # Log the failure
            log_validation_failure(
                topic=topic,
                category=CATEGORY,
                reason=",".join(last_validation_details.get("reasons", ["unknown"])),
                details=last_validation_details.get("details", {}),
                content=content,
            )
        else:
            word_count = len(content.split())
            if word_count >= MIN_WORDS:
                success, submission_id = submit_to_form(topic, CATEGORY, content)
                if success:
                    successful += 1
                    print(f"   {submission_id} ({word_count} words)")

                    # Log metadata
                    if METADATA_AVAILABLE:
                        try:
                            log_entry_metadata(
                                submission_id=submission_id,
                                source="cloudflare",
                                model=MODEL,
                                type="ai",
                                category=CATEGORY,
                                email=""
                            )
                            print(f"   [Metadata] Logged: {submission_id}")
                        except Exception as e:
                            print(f"   [Metadata] Failed to log: {e}")
                else:
                    failed += 1
                    print(f"   Submission failed")
            else:
                print(f"   Too short: {word_count} words (min {MIN_WORDS})")
                failed += 1

        if i < ENTRIES_PER_RUN:
            base_delay = random.randint(MIN_DELAY, MAX_DELAY)
            jitter = random.randint(1, 5)
            total_delay = base_delay + jitter
            print(f"   Waiting {total_delay}s (base {base_delay}s + jitter {jitter}s)...")
            sys.stdout.flush()
            time.sleep(total_delay)

    print(f"\n{'=' * 60}")
    print(f"Done: {successful} submitted | {failed} failed | {validation_rejected} rejected by validation")
    print("=" * 60)
    sys.stdout.flush()


if __name__ == "__main__":
    run()
