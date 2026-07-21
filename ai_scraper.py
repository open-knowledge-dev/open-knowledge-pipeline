"""
AI-Powered Knowledge Scraper — v2.1
====================================
Generates unique knowledge content using AI APIs with:
- Dynamic topic generation (no fixed lists)
- 8 rotating prompt styles for variety
- State file memory to avoid repeats
- Category weighting toward thin categories
- Markdown stripping for clean output
- Deduplication feedback loop

APIs: Groq (primary, 10/run), Mistral (fallback, 5/run)
"""

import os
import sys
import time
import random
import json
import base64
import requests
import re
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict


# ===========================================================================
# Configuration
# ===========================================================================

TRAINING_FORM_URL = os.getenv("TRAINING_FORM_URL", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
SUBMISSIONS_PER_RUN = int(os.getenv("SUBMISSIONS_PER_RUN", "10"))
SUBMISSION_DELAY = int(os.getenv("SUBMISSION_DELAY", "30"))
REQUEST_TIMEOUT = 60

GH_TOKEN = os.getenv("GH_TOKEN", "")
KNOWLEDGE_REPO = os.getenv("KNOWLEDGE_REPO", "")
GITHUB_API = "https://api.github.com"

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

FOCUS_CATEGORIES_RAW = os.getenv("FOCUS_CATEGORIES", "")
FOCUS_CATEGORIES = [c.strip() for c in FOCUS_CATEGORIES_RAW.split(",") if c.strip()]

ALL_CATEGORIES = [
    "Agriculture & Farming", "Business & Finance", "Culture & Traditions",
    "Education & Learning", "Health & Medicine", "Technology & Innovation",
    "Tourism & Travel", "History & Heritage", "Food & Cuisine",
    "Music & Dance", "Language & Proverbs", "Religion & Spirituality",
    "Sports & Games", "Fashion & Textiles", "Environment & Nature",
    "Governance & Leadership", "Family & Relationships", "Arts & Crafts",
    "Science & Innovation", "Other",
]

SCRAPER_NAME = os.getenv("SCRAPER_NAME", "ai-scraper")
STATE_FILE_PATH = "admin/scraper-state.json"


# ===========================================================================
# Prompt Styles — 8 different ways to ask for knowledge
# ===========================================================================

PROMPT_STYLES = [
    {
        "name": "explain-simply",
        "system": (
            "You are a patient teacher explaining things to a curious 15-year-old. "
            "Use simple words, real examples from daily life, and make it easy to understand. "
            "Write in first person as if sharing knowledge you learned from experience. "
            "Be warm, encouraging, and practical. Never mention AI. "
            "Do NOT use markdown formatting — no asterisks, no hashes, no underscores for bold or italics. "
            "Write in plain text only."
        ),
        "user_template": (
            'Explain "{topic}" in simple terms. '
            "Use examples from everyday life. Make it easy for anyone to understand. "
            "Write at least 670 words. Use plain text only — no markdown formatting."
        ),
    },
    {
        "name": "personal-story",
        "system": (
            "You are an elder sharing wisdom gained through a lifetime of experience. "
            "Write in first person with warmth and authority. Share real stories and lessons. "
            "Your knowledge comes from living, not books. Never mention AI. "
            "Do NOT use markdown formatting — no asterisks, no hashes, no underscores. "
            "Write in plain text only."
        ),
        "user_template": (
            'Share your personal knowledge and experience about "{topic}". '
            "Tell stories from real life. What have you learned? What works? What doesn't? "
            "Write at least 670 words. Use plain text only — no markdown formatting."
        ),
    },
    {
        "name": "compare-contrast",
        "system": (
            "You are an analytical thinker who compares different approaches. "
            "Write in first person. Show pros and cons of different methods. "
            "Be fair and balanced. Never mention AI. "
            "Do NOT use markdown formatting. Write in plain text only."
        ),
        "user_template": (
            'Compare different approaches to "{topic}". '
            "What are the pros and cons of each? Which works best in different situations? "
            "Write at least 670 words. Use plain text only."
        ),
    },
    {
        "name": "step-by-step",
        "system": (
            "You are a skilled practitioner teaching a craft. "
            "Give clear, numbered steps. Explain WHY each step matters. "
            "Write in first person. Be precise and practical. Never mention AI. "
            "Do NOT use markdown formatting. Write in plain text only."
        ),
        "user_template": (
            'Provide a step-by-step guide for "{topic}". '
            "Number each step. Explain why each step is important. "
            "Include practical tips from real experience. Write at least 670 words. "
            "Use plain text only — no markdown."
        ),
    },
    {
        "name": "historical-context",
        "system": (
            "You are a historian who understands how things evolved over time. "
            "Trace origins and changes. Show how the past connects to the present. "
            "Write in first person with rich detail. Never mention AI. "
            "Do NOT use markdown formatting. Write in plain text only."
        ),
        "user_template": (
            'Trace the history and evolution of "{topic}". '
            "How did it start? How has it changed? Where is it now? "
            "Write at least 670 words. Use plain text only."
        ),
    },
    {
        "name": "common-mistakes",
        "system": (
            "You are a seasoned expert who has seen people make every mistake possible. "
            "Share what goes wrong and how to avoid it. Be honest about failures. "
            "Write in first person. Never mention AI. "
            "Do NOT use markdown formatting. Write in plain text only."
        ),
        "user_template": (
            'What are the most common mistakes people make with "{topic}"? '
            "Explain each mistake clearly. How can they be avoided? "
            "Write at least 670 words. Use plain text only."
        ),
    },
    {
        "name": "regional-variations",
        "system": (
            "You are a well-traveled observer who notices how things differ across regions. "
            "Describe local variations and explain why they exist. "
            "Write in first person with rich observation. Never mention AI. "
            "Do NOT use markdown formatting. Write in plain text only."
        ),
        "user_template": (
            'Describe how "{topic}" differs across regions in Africa. '
            "What are the local variations? Why do they exist? "
            "Write at least 670 words. Use plain text only."
        ),
    },
    {
        "name": "future-outlook",
        "system": (
            "You are a forward-thinking expert who sees where things are heading. "
            "Discuss trends, challenges, and opportunities. Be realistic but hopeful. "
            "Write in first person. Never mention AI. "
            "Do NOT use markdown formatting. Write in plain text only."
        ),
        "user_template": (
            'Where is "{topic}" heading? Discuss current trends, future challenges, '
            "and what changes are coming. Write at least 670 words. Use plain text only."
        ),
    },
]


# ===========================================================================
# Markdown Stripping
# ===========================================================================

def strip_markdown(text: str) -> str:
    """
    Remove all markdown formatting from AI-generated text.
    Keeps the content, removes the formatting characters.
    """
    # Bold/italic: **text**, __text__, *text*, _text_
    text = re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+?)_{1,3}', r'\1', text)
    # Headers: ### Header, ## Header, # Header
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Bullet points: - item, * item
    text = re.sub(r'^[\-\*]\s+', '', text, flags=re.MULTILINE)
    # Numbered lists: 1. item -> 1. item (keep numbers, strip extra formatting)
    # Code blocks: ```code```
    text = re.sub(r'```[^`]*```', '', text)
    # Inline code: `code`
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Horizontal rules
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Extra whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ===========================================================================
# State File Operations
# ===========================================================================

def _github_headers() -> Dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GH_TOKEN:
        headers["Authorization"] = f"token {GH_TOKEN}"
    return headers


def load_state() -> Dict:
    if not GH_TOKEN or not KNOWLEDGE_REPO:
        return {}
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{STATE_FILE_PATH}"
    try:
        response = requests.get(url, headers=_github_headers(), timeout=15)
        if response.status_code == 200:
            content_b64 = response.json().get("content", "")
            if content_b64:
                decoded = base64.b64decode(content_b64).decode("utf-8")
                return json.loads(decoded)
    except Exception as e:
        print(f"  [State] Load failed: {e}")
    return {}


def save_state(state: Dict) -> bool:
    if not GH_TOKEN or not KNOWLEDGE_REPO:
        return False
    content_json = json.dumps(state, indent=2, default=str)
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{STATE_FILE_PATH}"
    sha = ""
    try:
        response = requests.get(url, headers=_github_headers(), timeout=10)
        if response.status_code == 200:
            sha = response.json().get("sha", "")
    except Exception:
        pass
    payload = {
        "message": f"Update scraper state: {SCRAPER_NAME}",
        "content": base64.b64encode(content_json.encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha
    try:
        response = requests.put(url, json=payload, headers=_github_headers(), timeout=15)
        return response.status_code in [200, 201]
    except Exception as e:
        print(f"  [State] Save error: {e}")
    return False


def get_last_topics(state: Dict, count: int = 30) -> List[str]:
    return state.get(SCRAPER_NAME, {}).get("last_topics", [])[-count:]


def record_topic(state: Dict, topic: str, submission_id: str, success: bool) -> Dict:
    if SCRAPER_NAME not in state:
        state[SCRAPER_NAME] = {
            "last_topics": [], "last_run": "", "total_submitted": 0,
            "total_failed": 0, "rejected_topics": [],
        }
    scraper = state[SCRAPER_NAME]
    scraper["last_topics"].append(topic)
    if len(scraper["last_topics"]) > 100:
        scraper["last_topics"] = scraper["last_topics"][-100:]
    if success:
        scraper["total_submitted"] += 1
    else:
        scraper["total_failed"] += 1
    scraper["last_run"] = datetime.now(timezone.utc).isoformat()
    return state


def record_rejected(state: Dict, topic: str) -> Dict:
    if SCRAPER_NAME not in state:
        state[SCRAPER_NAME] = {"rejected_topics": [], "last_topics": [], "last_run": "", "total_submitted": 0, "total_failed": 0}
    state[SCRAPER_NAME].setdefault("rejected_topics", []).append(topic)
    if len(state[SCRAPER_NAME]["rejected_topics"]) > 50:
        state[SCRAPER_NAME]["rejected_topics"] = state[SCRAPER_NAME]["rejected_topics"][-50:]
    return state


# ===========================================================================
# Category Awareness
# ===========================================================================

def get_category_counts() -> Dict[str, int]:
    category_slugs = {
        "Agriculture & Farming": "agriculture_farming",
        "Business & Finance": "business_finance",
        "Culture & Traditions": "culture_traditions",
        "Education & Learning": "education_learning",
        "Health & Medicine": "health_medicine",
        "Technology & Innovation": "technology_innovation",
        "Tourism & Travel": "tourism_travel",
        "History & Heritage": "history_heritage",
        "Food & Cuisine": "food_cuisine",
        "Music & Dance": "music_dance",
        "Language & Proverbs": "language_proverbs",
        "Religion & Spirituality": "religion_spirituality",
        "Sports & Games": "sports_games",
        "Fashion & Textiles": "fashion_textiles",
        "Environment & Nature": "environment_nature",
        "Governance & Leadership": "governance_leadership",
        "Family & Relationships": "family_relationships",
        "Arts & Crafts": "arts_crafts",
        "Science & Innovation": "science_innovation",
        "Other": "other",
    }
    counts = {}
    if not GH_TOKEN or not KNOWLEDGE_REPO:
        return counts
    for category_name, slug in category_slugs.items():
        url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{slug}"
        try:
            response = requests.get(url, headers=_github_headers(), timeout=10)
            if response.status_code == 200:
                data = response.json()
                counts[category_name] = len(data) if isinstance(data, list) else 0
            else:
                counts[category_name] = 0
        except Exception:
            counts[category_name] = 0
    return counts


def pick_category_weighted(counts: Dict[str, int], focus: List[str]) -> str:
    if not focus:
        focus = ALL_CATEGORIES
    available = {cat: counts.get(cat, 0) for cat in focus if cat in counts}
    if not available:
        return random.choice(focus)
    max_count = max(available.values()) + 1
    weighted = []
    for cat, count in available.items():
        weight = max_count - count
        weighted.extend([cat] * max(1, weight))
    return random.choice(weighted)


# ===========================================================================
# Dynamic Topic Generation
# ===========================================================================

def generate_topic(state: Dict, focus_categories: List[str]) -> Tuple[str, str]:
    last_topics = get_last_topics(state, 20)
    rejected = state.get(SCRAPER_NAME, {}).get("rejected_topics", [])[-20:]

    counts = get_category_counts()
    category = pick_category_weighted(counts, focus_categories)

    exclude_list = ""
    if last_topics or rejected:
        all_exclude = list(set(last_topics + rejected))[-30:]
        exclude_list = "Do NOT generate any of these topics:\n" + "\n".join(f"- {t}" for t in all_exclude) + "\n\n"

    system_prompt = (
        "You are a topic generator for a knowledge base about Africa. "
        "Generate ONE specific, narrow, practical topic. "
        "The topic should be something a real person would know from experience. "
        "Make it detailed — not broad like 'farming' but specific like "
        "'how small-scale farmers in northern Ghana test soil fertility without equipment'. "
        "Return ONLY the topic text, nothing else. No quotes, no explanation."
    )

    user_prompt = (
        f"{exclude_list}"
        f"Generate a unique, specific knowledge topic about {category}.\n"
        f"The topic must be narrow and practical.\n"
        f"Topic:"
    )

    topic_text = ""
    if GROQ_API_KEY:
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.95,
            "max_tokens": 80,
        }
        try:
            response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                topic_text = response.json()["choices"][0]["message"]["content"].strip().strip('"')
        except Exception as e:
            print(f"  [TopicGen] Groq failed: {e}")

    if not topic_text and MISTRAL_API_KEY:
        headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "mistral-small-latest",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.95,
            "max_tokens": 80,
        }
        try:
            response = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                topic_text = response.json()["choices"][0]["message"]["content"].strip().strip('"')
        except Exception as e:
            print(f"  [TopicGen] Mistral failed: {e}")

    if not topic_text or len(topic_text) < 10:
        fallbacks = [
            f"Traditional practices for {category.lower()} in West African communities",
            f"How {category.lower()} knowledge is passed between generations in rural areas",
            f"Practical tips for {category.lower()} from experienced community members",
            f"The role of {category.lower()} in daily life across different African regions",
            f"Lessons learned from decades of experience in {category.lower()}",
        ]
        topic_text = random.choice(fallbacks)

    return topic_text[:200], category


# ===========================================================================
# AI Content Generation
# ===========================================================================

def generate_with_groq(topic: str, category: str, style: Dict) -> str:
    if not GROQ_API_KEY:
        return ""
    print(f"    [Groq] Style: {style['name']}")
    sys.stdout.flush()
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    user_prompt = style["user_template"].replace("{topic}", topic)
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": style["system"]},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": random.uniform(0.7, 0.95),
        "max_tokens": 1500,
    }
    try:
        response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            print(f"    Generated {len(content)} chars")
            sys.stdout.flush()
            return content
        else:
            print(f"    Groq error: {response.status_code}")
            return ""
    except Exception as e:
        print(f"    Groq exception: {e}")
        return ""


def generate_with_mistral(topic: str, category: str, style: Dict) -> str:
    if not MISTRAL_API_KEY:
        return ""
    print(f"    [Mistral] Style: {style['name']}")
    sys.stdout.flush()
    headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
    user_prompt = style["user_template"].replace("{topic}", topic)
    payload = {
        "model": "mistral-small-latest",
        "messages": [
            {"role": "system", "content": style["system"]},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": random.uniform(0.7, 0.95),
        "max_tokens": 1500,
    }
    try:
        response = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            print(f"    Generated {len(content)} chars")
            sys.stdout.flush()
            return content
        else:
            print(f"    Mistral error: {response.status_code}")
            return ""
    except Exception as e:
        print(f"    Mistral exception: {e}")
        return ""


def generate_content(topic: str, category: str) -> str:
    style = random.choice(PROMPT_STYLES)

    if GROQ_API_KEY:
        content = generate_with_groq(topic, category, style)
        if content and len(content) > 300:
            return content

    if MISTRAL_API_KEY:
        content = generate_with_mistral(topic, category, style)
        if content and len(content) > 300:
            return content

    return ""


# ===========================================================================
# Submission
# ===========================================================================

def submit_to_form(topic: str, category: str, knowledge: str) -> Tuple[bool, str]:
    session = requests.Session()
    try:
        print(f"    Fetching form...")
        sys.stdout.flush()
        form_response = session.get(TRAINING_FORM_URL, timeout=REQUEST_TIMEOUT)
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

        app_check_token = SCRAPER_API_KEY if SCRAPER_API_KEY else ""

        submit_data = {
            "topic": topic, "category": category, "knowledge": knowledge,
            "region": "Various regions", "language": "English", "email": "",
            "verification_code": verification_code, "csrf_token": csrf_token,
            "app_check_token": app_check_token, "copyright_confirm": "on",
        }

        print(f"    Submitting...")
        sys.stdout.flush()
        submit_response = session.post(
            f"{TRAINING_FORM_URL}/submit", data=submit_data,
            timeout=REQUEST_TIMEOUT, allow_redirects=True,
        )

        if submit_response.status_code == 200:
            id_match = re.search(r'GHGPT-\d{4}-\d{4}', submit_response.text)
            submission_id = id_match.group(0) if id_match else "unknown"
            print(f"    Submitted! ID: {submission_id}")
            sys.stdout.flush()
            return True, submission_id
        else:
            print(f"    Failed. Status: {submit_response.status_code}")
            return False, ""
    except Exception as e:
        print(f"    ERROR: {e}")
        return False, ""


# ===========================================================================
# Main
# ===========================================================================

def run_ai_scraper(max_submissions: int = 10):
    print("=" * 60)
    print(f"AI Scraper v2.1 — {SCRAPER_NAME}")
    print("=" * 60)
    print(f"Target: {max_submissions} submissions")
    print(f"Focus: {FOCUS_CATEGORIES if FOCUS_CATEGORIES else 'All categories'}")
    print(f"Groq: {'ACTIVE' if GROQ_API_KEY else 'NOT SET'}")
    print(f"Mistral: {'ACTIVE' if MISTRAL_API_KEY else 'NOT SET'}")
    print(f"State: {'ENABLED' if GH_TOKEN else 'DISABLED'}")
    print("-" * 60)
    sys.stdout.flush()

    if not GROQ_API_KEY and not MISTRAL_API_KEY:
        print("ERROR: No API keys configured.")
        return

    state = load_state()
    print(f"  Previous submissions: {state.get(SCRAPER_NAME, {}).get('total_submitted', 0)}")

    submission_count = 0
    failed = 0
    used_topics = []

    for i in range(max_submissions):
        if submission_count >= max_submissions:
            break

        print(f"\n[{submission_count + 1}/{max_submissions}] Generating topic...")
        sys.stdout.flush()

        topic, category = generate_topic(state, FOCUS_CATEGORIES)
        print(f"  Topic: {topic}")
        print(f"  Category: {category}")
        sys.stdout.flush()

        knowledge = generate_content(topic, category)
        if not knowledge or len(knowledge) < 200:
            failed += 1
            print(f"  Failed to generate content")
            state = record_topic(state, topic, "", False)
            continue

        # Strip markdown formatting
        knowledge = strip_markdown(knowledge)

        # Strip AI disclaimers
        knowledge = re.sub(
            r'(?i)(as an AI|as a language model|I am an AI|based on my training|I cannot|I don\'t have personal)',
            '', knowledge
        ).strip()

        if len(knowledge) < 200:
            failed += 1
            state = record_topic(state, topic, "", False)
            continue

        print(f"  Content: {len(knowledge)} chars")
        sys.stdout.flush()

        success, submission_id = submit_to_form(topic, category, knowledge)

        if success:
            submission_count += 1
            used_topics.append(topic)
            state = record_topic(state, topic, submission_id, True)
        else:
            failed += 1
            state = record_topic(state, topic, "", False)
            if "already been submitted" in str(submission_id):
                state = record_rejected(state, topic)

        if GH_TOKEN:
            save_state(state)

        if submission_count < max_submissions and (i < max_submissions - 1):
            wait_time = SUBMISSION_DELAY + random.randint(1, 10)
            print(f"  Waiting {wait_time}s...")
            sys.stdout.flush()
            time.sleep(wait_time)

    print("\n" + "=" * 60)
    print(f"Done: {submission_count} submitted | {failed} failed")
    print(f"Topics: {used_topics}")
    print("=" * 60)


if __name__ == "__main__":
    is_automated = os.getenv("CI", "") == "true" or os.getenv("GITHUB_ACTIONS", "") == "true"
    if is_automated:
        count = SUBMISSIONS_PER_RUN
    else:
        confirm = input(f"\nHow many submissions? (default {SUBMISSIONS_PER_RUN}): ").strip()
        try:
            count = int(confirm) if confirm else SUBMISSIONS_PER_RUN
        except ValueError:
            count = SUBMISSIONS_PER_RUN
    print(f"\nStarting AI scraper with {count} submissions...\n")
    sys.stdout.flush()
    run_ai_scraper(max_submissions=count)
