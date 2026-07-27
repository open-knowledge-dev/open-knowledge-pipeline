"""
Tatoeba Scraper — Language Sentences
=====================================
Fetches sentence pairs from Tatoeba API (tatoeba.org).
Content licensed under CC-BY — safe for AI training.

Produces language knowledge entries for the Language & Proverbs category.
"""

import os
import sys
import time
import random
import json
import requests
import re
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict


TRAINING_FORM_URL = os.getenv("TRAINING_FORM_URL", "")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
SUBMISSIONS_PER_RUN = int(os.getenv("SUBMISSIONS_PER_RUN", "4"))
SUBMISSION_DELAY = int(os.getenv("SUBMISSION_DELAY", "30"))
REQUEST_TIMEOUT = 30
SCRAPER_NAME = os.getenv("SCRAPER_NAME", "web-tatoeba")

TATOEBA_API = "https://tatoeba.org/en/api"

LANGUAGES = [
    ("eng", "English"), ("fra", "French"), ("por", "Portuguese"),
    ("ara", "Arabic"), ("swa", "Swahili"), ("hau", "Hausa"),
    ("yor", "Yoruba"), ("ibo", "Igbo"), ("zul", "Zulu"),
    ("amh", "Amharic"), ("som", "Somali"), ("twi", "Twi"),
    ("ewe", "Ewe"), ("lin", "Lingala"), ("kin", "Kinyarwanda"),
]


def fetch_sentences(lang_code: str, limit: int = 10) -> List[Dict]:
    """Fetch sentences from Tatoeba API for a given language."""
    url = f"{TATOEBA_API}/search"
    params = {"from": "eng", "to": lang_code, "limit": limit}
    headers = {"User-Agent": "GhanaGPT-Tatoeba/1.0"}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            return data.get("results", [])
        print(f"    Tatoeba API returned {response.status_code}")
        return []
    except Exception as e:
        print(f"    Tatoeba error: {e}")
        return []


def submit_to_form(topic: str, category: str, knowledge: str, language: str) -> Tuple[bool, str]:
    """Submit knowledge to the training form."""
    session = requests.Session()
    try:
        print(f"    Fetching form...")
        sys.stdout.flush()
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
            "topic": topic, "category": category, "knowledge": knowledge,
            "region": "", "language": language, "email": "",
            "verification_code": verification_code, "csrf_token": csrf_token,
            "app_check_token": SCRAPER_API_KEY, "copyright_confirm": "on",
        }

        submit_response = session.post(
            f"{TRAINING_FORM_URL}/submit", data=submit_data,
            timeout=REQUEST_TIMEOUT, allow_redirects=True,
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


def run_scraper():
    """Main scraper loop."""
    print("=" * 60)
    print(f"Tatoeba Scraper — {SCRAPER_NAME}")
    print("=" * 60)
    print(f"Target: {SUBMISSIONS_PER_RUN} submissions")
    sys.stdout.flush()

    submission_count = 0
    random.shuffle(LANGUAGES)

    for lang_code, lang_name in LANGUAGES:
        if submission_count >= SUBMISSIONS_PER_RUN:
            break

        print(f"\n[{submission_count + 1}/{SUBMISSIONS_PER_RUN}] Language: {lang_name}")
        sentences = fetch_sentences(lang_code)

        if not sentences:
            print(f"    No sentences found")
            continue

        # Build knowledge from sentences
        lines = []
        for item in sentences[:10]:
            eng = item.get("text", "")
            trans = item.get("translation", {}).get("text", "")
            if eng and trans:
                lines.append(f"{eng}\n→ {trans}")

        if len(lines) < 3:
            continue

        knowledge = f"Learning {lang_name} through common phrases:\n\n"
        knowledge += "\n\n".join(lines)
        knowledge += f"\n\nThese are everyday phrases in {lang_name}. Practice them regularly to build your vocabulary and confidence."

        topic = f"Common {lang_name} phrases with English translations"
        print(f"  Topic: {topic}")
        print(f"  Content: {len(knowledge)} chars")
        sys.stdout.flush()

        success, sid = submit_to_form(topic, "Language & Proverbs", knowledge, lang_name)
        if success:
            submission_count += 1

        if submission_count < SUBMISSIONS_PER_RUN:
            time.sleep(SUBMISSION_DELAY)

    print(f"\nDone: {submission_count} submitted")
    print("=" * 60)


if __name__ == "__main__":
    run_scraper()
