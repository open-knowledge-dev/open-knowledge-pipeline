"""
Cloudflare Workers AI Scraper — v2.0
=====================================
Uses Cloudflare Workers AI free tier to generate knowledge entries.
Submits through the training form — same pipeline as all other scrapers.
Never writes files locally. Never exposes knowledge publicly.

Models: Llama 8B, Mistral 7B, Llama 70B, Qwen3 30B
Free tier: 10,000 requests/day
"""

import os
import sys
import re
import time
import random
import requests
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))

from topics import TOPICS
from prompts import PROMPTS


ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
MODEL = os.environ.get("CLOUDFLARE_MODEL", "@cf/meta/llama-3.1-8b-instruct-fp8")
CATEGORY = os.environ.get("SCRAPER_CATEGORY", "Culture & Traditions")

TRAINING_FORM_URL = os.environ.get("TRAINING_FORM_URL", "")
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")

BASE_URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run"

ENTRIES_PER_RUN = int(os.environ.get("ENTRIES_PER_RUN", "10"))
MIN_WORDS = int(os.environ.get("MIN_WORDS", "400"))
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "1500"))
TEMPERATURE = 0.75
MIN_DELAY = 10
MAX_DELAY = 20
REQUEST_TIMEOUT = 90


def generate_entry(topic, prompt_template, model):
    """Call Cloudflare Workers AI API and return generated text."""
    prompt = prompt_template.format(topic=topic)

    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE
    }

    url = f"{BASE_URL}/{model}"

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if data.get("success") and "result" in data:
            text = data["result"]["response"]
            if text.startswith("```"):
                lines = text.split("\n")
                lines = lines[1:] if lines else lines
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines)
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


def clean_content(text):
    """Clean generated text — remove common AI artifacts."""
    prefixes = [
        "Here is a detailed",
        "Here is an article",
        "Here's a comprehensive",
        "Here's an overview",
        "Certainly!",
        "Of course!",
        "Below is a",
        "The following is a",
    ]
    for prefix in prefixes:
        if text.lower().startswith(prefix.lower()):
            first_break = text.find("\n\n")
            if first_break > 0:
                text = text[first_break:].strip()
            break

    text = re.sub(
        r'(?i)(as an AI|as a language model|I am an AI|based on my training|I cannot|I don\'t have personal)',
        '', text
    ).strip()

    return text


def submit_to_form(topic, category, knowledge, language="English"):
    """Submit knowledge to the training form — same pipeline as all scrapers."""
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


def run():
    """Main scraper loop."""
    print("=" * 60)
    print("Cloudflare Workers AI Scraper v2.0")
    print("=" * 60)
    print(f"Model: {MODEL}")
    print(f"Category: {CATEGORY}")
    print(f"Entries per run: {ENTRIES_PER_RUN}")
    print(f"Topic pool: {len(TOPICS)} topics")
    print(f"Prompt styles: {len(PROMPTS)} templates")
    print(f"Submitting to: {TRAINING_FORM_URL}")
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

    for i, topic in enumerate(shuffled_topics[:ENTRIES_PER_RUN], 1):
        prompt = random.choice(PROMPTS)

        print(f"\n[{i}/{ENTRIES_PER_RUN}] {topic[:80]}...")
        print(f"   Model: {MODEL}")
        sys.stdout.flush()

        content = generate_entry(topic, prompt, MODEL)

        if content:
            content = clean_content(content)
            word_count = len(content.split())

            if word_count >= MIN_WORDS:
                success, submission_id = submit_to_form(
                    topic, CATEGORY, content
                )
                if success:
                    successful += 1
                    print(f"   {submission_id} ({word_count} words)")
                else:
                    failed += 1
                    print(f"   Submission failed")
            else:
                print(f"   Too short: {word_count} words (min {MIN_WORDS})")
                failed += 1
        else:
            failed += 1

        if i < ENTRIES_PER_RUN:
            delay = random.randint(MIN_DELAY, MAX_DELAY)
            print(f"   Waiting {delay}s...")
            sys.stdout.flush()
            time.sleep(delay)

    print(f"\n{'=' * 60}")
    print(f"Done: {successful} submitted | {failed} failed")
    print("=" * 60)
    sys.stdout.flush()


if __name__ == "__main__":
    run()
