"""
One-time importer — submits all pending backup files to the training form.
Reads files from pending_backup/, submits through training.ghana-gpt.com/submit.
Deletes files after successful submission. Self-deletes when done.
Runs until the folder is empty.
"""

import os
import sys
import re
import time
import requests


TRAINING_FORM_URL = os.environ.get("TRAINING_FORM_URL", "")
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")
BACKUP_DIR = "pending_backup"
BATCH_SIZE = 25
DELAY = 3


def extract_content(filepath):
    """Extract topic, category, and knowledge from a markdown file."""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    category = "Other"
    cat_match = re.search(r'<!-- category:\s*(.+?) -->', text)
    if cat_match:
        cat = cat_match.group(1).strip()
        cat_map = {
            "culture": "Culture & Traditions",
            "agriculture": "Agriculture & Farming",
            "food": "Food & Cuisine",
            "health": "Health & Medicine",
            "history": "History & Heritage",
            "language": "Language & Proverbs",
            "music": "Music & Dance",
            "business": "Business & Finance",
            "governance": "Governance & Leadership",
            "environment": "Environment & Nature",
            "technology": "Technology & Innovation",
            "education": "Education & Learning",
            "sports": "Sports & Games",
            "fashion": "Fashion & Textiles",
            "arts": "Arts & Crafts",
            "science": "Science & Innovation",
            "religion": "Religion & Spirituality",
            "tourism": "Tourism & Travel",
            "family": "Family & Relationships",
        }
        category = cat_map.get(cat.lower(), "Culture & Traditions")

    topic = "Knowledge Entry"
    topic_match = re.search(r'^#\s+(.+)', text, re.MULTILINE)
    if topic_match:
        topic = topic_match.group(1).strip()[:200]

    content = text
    content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    content = re.sub(r'^#\s+.+', '', content, flags=re.MULTILINE)
    content = content.strip()

    return topic, category, content


def submit_to_form(topic, category, knowledge):
    """Submit to training form — same pipeline as all scrapers."""
    session = requests.Session()
    try:
        form_response = session.get(TRAINING_FORM_URL, timeout=30)
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
            "language": "English",
            "email": "",
            "verification_code": verification_code,
            "csrf_token": csrf_token,
            "app_check_token": SCRAPER_API_KEY,
            "copyright_confirm": "on",
        }

        submit_response = session.post(
            f"{TRAINING_FORM_URL}/submit",
            data=submit_data,
            timeout=30,
            allow_redirects=True,
        )

        if submit_response.status_code == 200:
            id_match = re.search(r'GHGPT-\d{4}-\d{4}', submit_response.text)
            return True, id_match.group(0) if id_match else "unknown"
        return False, ""
    except Exception:
        return False, ""


def run():
    if not os.path.isdir(BACKUP_DIR):
        print(f"ERROR: {BACKUP_DIR}/ folder not found. Nothing to import.")
        sys.exit(0)

    files = [f for f in os.listdir(BACKUP_DIR) if f.endswith(".md")]
    
    if not files:
        print("No files left. Cleaning up.")
        os.rmdir(BACKUP_DIR)
        return

    print(f"Found {len(files)} files. Processing up to {BATCH_SIZE} this run.")
    print("-" * 50)

    submitted = 0
    failed = 0
    batch = files[:BATCH_SIZE]

    for i, filename in enumerate(batch, 1):
        filepath = os.path.join(BACKUP_DIR, filename)
        print(f"[{i}/{len(batch)}] {filename[:60]}...", end=" ")
        sys.stdout.flush()

        topic, category, content = extract_content(filepath)

        if len(content) < 100:
            print("SKIP (too short)")
            failed += 1
            os.remove(filepath)
            continue

        success, sid = submit_to_form(topic, category, content)
        if success:
            print(sid)
            submitted += 1
            os.remove(filepath)
        else:
            print("FAIL")
            failed += 1

        if i < len(batch):
            time.sleep(DELAY)

    remaining = len([f for f in os.listdir(BACKUP_DIR) if f.endswith(".md")])
    print(f"\nDone: {submitted} submitted | {failed} failed | {remaining} remaining")
    
    if remaining == 0:
        os.rmdir(BACKUP_DIR)
        print("All files imported. pending_backup/ deleted.")


if __name__ == "__main__":
    run()
