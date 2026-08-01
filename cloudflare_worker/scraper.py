#!/usr/bin/env python3
"""Cloudflare Workers AI Scraper for Ghana-GPT Knowledge Pipeline.
Uses Cloudflare Workers AI free tier to generate knowledge entries.
Outputs markdown files to the pending/ folder."""

import os
import sys
import json
import time
import random
import hashlib
import requests
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for shared utilities
sys.path.insert(0, str(Path(__file__).parent.parent))

from cloudflare_worker.topics import TOPICS
from cloudflare_worker.prompts import PROMPTS

# --- CONFIGURATION ---
ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
MODEL = os.environ.get("CLOUDFLARE_MODEL", "@cf/qwen/qwen2.5-7b-instruct")
CATEGORY = os.environ.get("SCRAPER_CATEGORY", "general")

BASE_URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run"

# Settings
ENTRIES_PER_RUN = int(os.environ.get("ENTRIES_PER_RUN", "10"))
MIN_WORDS = 400
MAX_TOKENS = 1500
TEMPERATURE = 0.75
MIN_DELAY = 10
MAX_DELAY = 20
PENDING_DIR = "pending"

# Database logging (reuse same pattern as other scrapers)
# Import your existing DB utilities if available
try:
    from db_utils import log_to_databases
    DB_ENABLED = True
except ImportError:
    DB_ENABLED = False
    print("⚠️ db_utils not found — skipping database logging")


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
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        data = response.json()
        
        if data.get("success") and "result" in data:
            text = data["result"]["response"]
            # Strip any markdown code blocks from response
            if text.startswith("```"):
                lines = text.split("\n")
                lines = lines[1:] if lines else lines
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines)
            return text.strip()
        else:
            errors = data.get("errors", [])
            print(f"  ❌ API error: {errors}")
            return None
            
    except requests.exceptions.Timeout:
        print(f"  ❌ Request timed out")
        return None
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Request failed: {e}")
        return None


def clean_content(text):
    """Clean generated text — remove common AI artifacts."""
    # Remove phrases like "Here is a detailed article about..."
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
            # Find first newline and trim
            first_break = text.find("\n\n")
            if first_break > 0:
                text = text[first_break:].strip()
            break
    
    return text


def save_entry(content, topic, model, category):
    """Save generated content as markdown file to pending folder."""
    
    os.makedirs(PENDING_DIR, exist_ok=True)
    
    # Generate safe filename
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    topic_slug = topic.lower().replace(" ", "_").replace("/", "-")[:60]
    content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
    filename = f"{PENDING_DIR}/cf_{category}_{topic_slug}_{timestamp}_{content_hash}.md"
    
    word_count = len(content.split())
    
    # Build markdown with metadata
    metadata = f"""<!-- meta -->
<!-- source: cloudflare_workers_ai -->
<!-- model: {model} -->
<!-- category: {category} -->
<!-- date: {datetime.now(timezone.utc).isoformat()} -->
<!-- region:  -->
<!-- language: en -->
<!-- words: {word_count} -->
<!-- scraper: cloudflare_worker -->
<!-- -->
"""
    
    full_content = f"{metadata}\n# {topic.title()}\n\n{content}\n"
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(full_content)
    
    return filename, word_count


def log_metadata(filename, topic, model, category, word_count):
    """Log entry metadata to all 3 databases — matching existing scraper pattern."""
    if not DB_ENABLED:
        return
    
    metadata = {
        "filename": filename,
        "topic": topic,
        "source": "cloudflare_workers_ai",
        "model": model,
        "category": category,
        "words": word_count,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    
    try:
        log_to_databases(metadata)
    except Exception as e:
        print(f"  ⚠️ Database logging failed (non-fatal): {e}")


def run():
    """Main scraper loop."""
    
    print(f"🚀 Cloudflare Workers AI Scraper")
    print(f"   Model: {MODEL}")
    print(f"   Category: {CATEGORY}")
    print(f"   Entries per run: {ENTRIES_PER_RUN}")
    print(f"   Topic pool: {len(TOPICS)} topics")
    print(f"   Prompt styles: {len(PROMPTS)} templates")
    print()
    
    if not ACCOUNT_ID or not API_TOKEN:
        print("❌ Missing CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_API_TOKEN")
        sys.exit(1)
    
    # Shuffle topics for variety
    shuffled_topics = TOPICS.copy()
    random.shuffle(shuffled_topics)
    
    successful = 0
    failed = 0
    
    for i, topic in enumerate(shuffled_topics[:ENTRIES_PER_RUN], 1):
        prompt = random.choice(PROMPTS)
        
        print(f"[{i}/{ENTRIES_PER_RUN}] {topic[:80]}...")
        print(f"   Model: {MODEL}")
        
        content = generate_entry(topic, prompt, MODEL)
        
        if content:
            content = clean_content(content)
            word_count = len(content.split())
            
            if word_count >= MIN_WORDS:
                filename, wc = save_entry(content, topic, MODEL, CATEGORY)
                log_metadata(filename, topic, MODEL, CATEGORY, wc)
                print(f"   ✅ Saved: {filename} ({wc} words)")
                successful += 1
            else:
                print(f"   ⚠️ Too short: {word_count} words (min {MIN_WORDS})")
                failed += 1
        else:
            failed += 1
        
        # Rate limiting
        if i < ENTRIES_PER_RUN:
            delay = random.randint(MIN_DELAY, MAX_DELAY)
            print(f"   ⏳ Waiting {delay}s...")
            time.sleep(delay)
    
    print(f"\n📊 Done. {successful} successful, {failed} failed out of {ENTRIES_PER_RUN} attempts.")


if __name__ == "__main__":
    run()
