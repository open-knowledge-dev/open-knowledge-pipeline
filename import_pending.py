"""
One-time importer — submits existing pending files to the training form.
Reads files from a local pending_backup/ folder, extracts content,
and submits through training.ghana-gpt.com/submit.
Delete this file and the backup folder after the import completes.
"""

import os
import sys
import re
import time
import requests


TRAINING_FORM_URL = os.environ.get("TRAINING_FORM_URL", "")
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")
BACKUP_DIR = "pending_backup"
ENTRIES_PER_RUN = 25
DELAY = 5


def extract_content(filepath):
    """Extract topic, category, and knowledge from a markdown file."""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    category = "Other"
    cat_match = re.search(r'<!-- category:\s*(.+?) -->', text)
    if cat_match:
        category = cat_match.group(1).strip()

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
    """Submit to training form."""
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
        print(f"ERROR: {BACKUP_DIR}/ folder not found.")
        sys.exit(1)

    files = [f for f in os.listdir(BACKUP_DIR) if f.endswith(".md")]
    print(f"Found {len(files)} files to import.")
    print(f"Submitting {ENTRIES_PER_RUN} per run.")
    print("-" * 50)

    submitted = 0
    failed = 0

    for i, filename in enumerate(files[:ENTRIES_PER_RUN], 1):
        filepath = os.path.join(BACKUP_DIR, filename)
        print(f"[{i}/{min(len(files), ENTRIES_PER_RUN)}] {filename[:60]}...", end=" ")

        topic, category, content = extract_content(filepath)

        if len(content) < 100:
            print("SKIP (too short)")
            failed += 1
            continue

        success, sid = submit_to_form(topic, category, content)
        if success:
            print(f"OK ({sid})")
            submitted += 1
            os.remove(filepath)
        else:
            print("FAIL")
            failed += 1

        if i < min(len(files), ENTRIES_PER_RUN):
            time.sleep(DELAY)

    print(f"\nDone: {submitted} submitted | {failed} failed")
    remaining = len([f for f in os.listdir(BACKUP_DIR) if f.endswith(".md")])
    print(f"Remaining: {remaining}")
    if remaining == 0:
        print("All files imported. You can delete the pending_backup/ folder.")


if __name__ == "__main__":
    run()
