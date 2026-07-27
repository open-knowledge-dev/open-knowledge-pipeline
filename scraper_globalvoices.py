"""
Global Voices Scraper — Multilingual News
==========================================
Fetches articles from Global Voices RSS feed (globalvoices.org).
Content licensed under CC-BY — safe for AI training.

Produces knowledge entries for Culture, Governance, and related categories.
"""

import os
import sys
import time
import random
import json
import requests
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict


TRAINING_FORM_URL = os.getenv("TRAINING_FORM_URL", "")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
SUBMISSIONS_PER_RUN = int(os.getenv("SUBMISSIONS_PER_RUN", "4"))
SUBMISSION_DELAY = int(os.getenv("SUBMISSION_DELAY", "30"))
REQUEST_TIMEOUT = 30
SCRAPER_NAME = os.getenv("SCRAPER_NAME", "web-globalvoices")

RSS_FEED = "https://globalvoices.org/feed/"


def fetch_articles() -> List[Dict]:
    """Fetch articles from Global Voices RSS feed."""
    articles = []
    try:
        response = requests.get(RSS_FEED, timeout=REQUEST_TIMEOUT,
                                headers={"User-Agent": "GhanaGPT-GlobalVoices/1.0"})
        if response.status_code != 200:
            return articles

        root = ET.fromstring(response.content)
        for item in root.findall(".//item"):
            title = item.findtext("title", "")
            description = item.findtext("description", "")
            link = item.findtext("link", "")
            if title and description:
                clean_desc = re.sub(r'<[^>]+>', ' ', description)
                clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()
                if len(clean_desc) > 200:
                    articles.append({
                        "title": title,
                        "content": clean_desc[:2000],
                        "url": link,
                    })
    except Exception as e:
        print(f"    RSS error: {e}")
    return articles


def submit_to_form(topic: str, category: str, knowledge: str) -> Tuple[bool, str]:
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
            "region": "", "language": "English", "email": "",
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


def determine_category(title: str) -> str:
    """Determine category based on article title."""
    title_lower = title.lower()
    if any(w in title_lower for w in ["government", "law", "policy", "election"]):
        return "Governance & Leadership"
    if any(w in title_lower for w in ["culture", "tradition", "festival", "art"]):
        return "Culture & Traditions"
    if any(w in title_lower for w in ["business", "economy", "market", "trade"]):
        return "Business & Finance"
    if any(w in title_lower for w in ["environment", "climate", "forest"]):
        return "Environment & Nature"
    if any(w in title_lower for w in ["health", "disease", "medicine"]):
        return "Health & Medicine"
    return "Culture & Traditions"


def run_scraper():
    """Main scraper loop."""
    print("=" * 60)
    print(f"Global Voices Scraper — {SCRAPER_NAME}")
    print("=" * 60)
    print(f"Target: {SUBMISSIONS_PER_RUN} submissions")
    sys.stdout.flush()

    articles = fetch_articles()
    print(f"Found {len(articles)} articles")
    random.shuffle(articles)

    submission_count = 0
    for article in articles:
        if submission_count >= SUBMISSIONS_PER_RUN:
            break

        topic = article["title"][:200]
        category = determine_category(topic)
        content = article["content"]

        # Rewrite in conversational voice
        starters = [
            "I read something interesting about this recently.",
            "People are talking about this across Africa.",
            "Here is what is happening in our world.",
        ]
        knowledge = f"{random.choice(starters)}\n\n{content}\n\nThis information matters for understanding how our world is changing."

        print(f"  Topic: {topic[:60]}...")
        print(f"  Category: {category}")
        print(f"  Content: {len(knowledge)} chars")
        sys.stdout.flush()

        success, sid = submit_to_form(topic, category, knowledge)
        if success:
            submission_count += 1

        if submission_count < SUBMISSIONS_PER_RUN:
            time.sleep(SUBMISSION_DELAY)

    print(f"\nDone: {submission_count} submitted")
    print("=" * 60)


if __name__ == "__main__":
    run_scraper()
