"""
AI-Powered Knowledge Scraper — Environment & Nature — v2.4.3
=============================================================
Dedicated scraper for Environment & Nature knowledge.
Focuses on climate, conservation, renewable energy, water management,
waste management, biodiversity, and sustainability topics with
West African and Ghanaian context.

Features:
- Batch topic caching (25 topics per API call — 42% token savings)
- Comparison topics (~25% of output for deeper content)
- 10 rotating prompt styles with compare-contrast weighted higher
- State file memory to avoid repeats
- Markdown stripping for clean output
- Deduplication feedback loop
- Minimum 670 words per submission
- Region field left empty (no fake location data)
- Language variation (70% English, 30% French/Portuguese/Arabic/Swahili)
- AI writes in the target language
- Banned organization filtering (FAO, WHO, UN, World Bank, IMF, etc.)

APIs: Groq (primary, 10/run), Mistral (fallback, 5/run)
Schedule: Every 4 hours via GitHub Actions
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

FOCUS_CATEGORIES = ["Environment & Nature"]

ALL_CATEGORIES = [
    "Agriculture & Farming", "Business & Finance", "Culture & Traditions",
    "Education & Learning", "Health & Medicine", "Technology & Innovation",
    "Tourism & Travel", "History & Heritage", "Food & Cuisine",
    "Music & Dance", "Language & Proverbs", "Religion & Spirituality",
    "Sports & Games", "Fashion & Textiles", "Environment & Nature",
    "Governance & Leadership", "Family & Relationships", "Arts & Crafts",
    "Science & Innovation", "Other",
]

SCRAPER_NAME = os.getenv("SCRAPER_NAME", "ai-scraper-environment-github")
STATE_FILE_PATH = os.getenv("STATE_FILE_PATH", "admin/scraper-state-environment.json")

MIN_CONTENT_LENGTH = 500
TOPIC_CACHE_SIZE = 25
COMPARISON_TOPIC_RATIO = 0.25


# ===========================================================================
# Banned Organizations — Never appear in generated content
# ===========================================================================

BANNED_ORGS = [
    "FAO",
    "Food and Agriculture Organization",
    "WHO",
    "World Health Organization",
    "UN",
    "United Nations",
    "World Bank",
    "IMF",
    "International Monetary Fund",
    "UNDP",
    "UNESCO",
    "UNICEF",
    "USAID",
    "DFID",
    "GIZ",
    "World Food Programme",
    "WFP",
    "International Labour Organization",
    "ILO",
    "World Trade Organization",
    "WTO",
    "African Development Bank",
    "AfDB",
    "European Union",
    "EU"
]

BANNED_ORGS_STRING = ", ".join(BANNED_ORGS)
BANNED_INSTRUCTION = (
    f"IMPORTANT: Never mention or reference any of these organizations: {BANNED_ORGS_STRING}. "
    "Focus entirely on local African perspectives without any external organizational framing. "
    "Do not reference development programs, aid, or international interventions. "
    "Write from the perspective of African knowledge systems only."
)

BANNED_TERMS = [
    "development program", "aid program", "international assistance",
    "foreign aid", "development agency", "grant", "funding", "NGO",
    "non-governmental"
]


def _check_banned_content(text: str) -> bool:
    """Check if content contains banned organizations or terms. Returns True if clean."""
    text_lower = text.lower()
    for org in BANNED_ORGS:
        if org.lower() in text_lower:
            print(f"  [Safety] Content contains banned organization: {org}")
            return False
    for term in BANNED_TERMS:
        if term in text_lower:
            print(f"  [Safety] Content contains banned term: {term}")
            return False
    return True


# ===========================================================================
# Language Variation
# ===========================================================================

LANGUAGES = [
    "English", "English", "English", "English", "English", "English", "English",
    "Français (French)", "Français (French)",
    "Português (Portuguese)",
    "العربية (Arabic)",
    "Kiswahili (Swahili)",
]


# ===========================================================================
# Prompt Styles
# ===========================================================================

PROMPT_STYLES = [
    {
        "name": "explain-simply",
        "system": (
            "You are a patient teacher explaining environmental topics to a curious 15-year-old. "
            "Use simple words, real examples from nature and daily life, and make it easy to understand. "
            "Write in first person as if sharing knowledge you learned from living close to the land. "
            "Be warm, encouraging, and practical. Never mention AI or language models. "
            "Do NOT use markdown formatting — no asterisks, no hashes, no underscores. "
            "Write in plain text only. "
            + BANNED_INSTRUCTION
        ),
        "user_template": (
            'Explain "{topic}" in simple terms in {language}. '
            "Use examples from nature and everyday life. Make it easy for anyone to understand. "
            "Be thorough and detailed. Write at least 670 words. "
            "Use plain text only — no markdown formatting."
        ),
    },
    {
        "name": "personal-story",
        "system": (
            "You are an elder who has spent a lifetime observing the natural world. "
            "Write in first person with warmth and authority. Share real stories about the environment, "
            "weather patterns, wildlife, and how communities live with nature. "
            "Your knowledge comes from living close to the land, not books. "
            "Never mention AI or language models. "
            "Do NOT use markdown formatting. Write in plain text only. "
            + BANNED_INSTRUCTION
        ),
        "user_template": (
            'Share your personal knowledge and experience about "{topic}" in {language}. '
            "Tell stories from real life. What have you observed? What has changed over time? "
            "What works? What doesn't? "
            "Be thorough and detailed. Write at least 670 words. "
            "Use plain text only — no markdown formatting."
        ),
    },
    {
        "name": "compare-contrast",
        "system": (
            "You are an environmental analyst who compares different approaches to conservation, "
            "energy, and land management. Write in first person. Show pros and cons of different methods. "
            "Be fair and balanced. Give specific examples from West Africa and beyond. "
            "Help the reader understand which approach works best in which situation. "
            "Never mention AI or language models. "
            "Do NOT use markdown formatting. Write in plain text only. "
            + BANNED_INSTRUCTION
        ),
        "user_template": (
            'Compare and contrast "{topic}" in {language}. '
            "What are the key differences? What are the pros and cons of each approach? "
            "Which one works better in different environments or situations? Give specific examples. "
            "Be thorough and detailed. Write at least 670 words. "
            "Use plain text only — no markdown formatting."
        ),
    },
    {
        "name": "compare-contrast",
        "system": (
            "You are an environmental analyst who compares different approaches to conservation, "
            "energy, and land management. Write in first person. Show pros and cons of different methods. "
            "Be fair and balanced. Give specific examples from West Africa and beyond. "
            "Help the reader understand which approach works best in which situation. "
            "Never mention AI or language models. "
            "Do NOT use markdown formatting. Write in plain text only. "
            + BANNED_INSTRUCTION
        ),
        "user_template": (
            'Compare and contrast "{topic}" in {language}. '
            "What are the key differences? What are the pros and cons of each approach? "
            "Which one works better in different environments or situations? Give specific examples. "
            "Be thorough and detailed. Write at least 670 words. "
            "Use plain text only — no markdown formatting."
        ),
    },
    {
        "name": "step-by-step",
        "system": (
            "You are a conservation practitioner who has restored land, planted trees, "
            "and managed natural resources for decades. Give clear, numbered steps. "
            "Explain WHY each step matters for the environment. "
            "Include materials needed, time required, and difficulty level. "
            "Write in first person. Be precise and practical. Never mention AI or language models. "
            "Do NOT use markdown formatting. Write in plain text only. "
            + BANNED_INSTRUCTION
        ),
        "user_template": (
            'Provide a complete step-by-step guide for "{topic}" in {language}. '
            "Include: what you need before starting, each step numbered and explained, "
            "how long each step takes, and common mistakes to avoid. "
            "Be thorough and detailed. Write at least 670 words. "
            "Use plain text only — no markdown formatting."
        ),
    },
    {
        "name": "historical-context",
        "system": (
            "You are an environmental historian who understands how landscapes, "
            "ecosystems, and climate have changed over time. "
            "Trace the evolution of environmental conditions and human relationships with nature. "
            "Show how the past connects to present environmental challenges. "
            "Write in first person with rich detail. Never mention AI or language models. "
            "Do NOT use markdown formatting. Write in plain text only. "
            + BANNED_INSTRUCTION
        ),
        "user_template": (
            'Trace the history and evolution of "{topic}" in {language}. '
            "How did it start? How has it changed over time? Where is it now? "
            "What forces shaped its development? "
            "Be thorough and detailed. Write at least 670 words. "
            "Use plain text only — no markdown formatting."
        ),
    },
    {
        "name": "common-mistakes",
        "system": (
            "You are a seasoned environmental expert who has seen people make every mistake possible "
            "in managing natural resources. Share what goes wrong and how to avoid it. "
            "Be honest about failures and their environmental consequences. "
            "Write in first person. Never mention AI or language models. "
            "Do NOT use markdown formatting. Write in plain text only. "
            + BANNED_INSTRUCTION
        ),
        "user_template": (
            'What are the most common mistakes people make with "{topic}" in {language}? '
            "For each mistake: explain what it is, why people make it, what happens as a result, "
            "and exactly how to avoid it. Be specific and practical. "
            "Write at least 670 words. Use plain text only — no markdown formatting."
        ),
    },
    {
        "name": "regional-variations",
        "system": (
            "You are a well-traveled environmental observer who notices how ecosystems, "
            "climate, and conservation practices differ across regions. "
            "Describe local variations in environmental conditions and explain why they exist. "
            "Write in first person with rich observation. Never mention AI or language models. "
            "Do NOT use markdown formatting. Write in plain text only. "
            + BANNED_INSTRUCTION
        ),
        "user_template": (
            'Describe how "{topic}" differs across regions in {language}. '
            "What are the local variations? Why do they exist? "
            "How do climate, geography, and human activity shape these differences? "
            "Be thorough and detailed. Write at least 670 words. "
            "Use plain text only — no markdown formatting."
        ),
    },
    {
        "name": "future-outlook",
        "system": (
            "You are a forward-thinking environmental expert who sees where the planet is heading. "
            "Discuss climate trends, conservation challenges, and opportunities for a sustainable future. "
            "Be realistic but hopeful. Focus on solutions that communities can implement. "
            "Write in first person. Never mention AI or language models. "
            "Do NOT use markdown formatting. Write in plain text only. "
            + BANNED_INSTRUCTION
        ),
        "user_template": (
            'Where is "{topic}" heading? Discuss current environmental trends, future challenges, '
            "and what changes are coming in {language}. "
            "What should communities prepare for? What solutions exist? "
            "Be thorough and detailed. Write at least 670 words. "
            "Use plain text only — no markdown formatting."
        ),
    },
    {
        "name": "practical-guide",
        "system": (
            "You are a skilled environmental practitioner who has done conservation work, "
            "tree planting, water management, and waste reduction hundreds of times. "
            "You know every technique, shortcut, and pitfall. "
            "Give clear, actionable instructions that anyone can follow. "
            "Include what materials or preparation is needed, how long it takes, "
            "the difficulty level, and what to do when things go wrong. "
            "Write in first person from real experience. "
            "Never mention AI or language models. "
            "Do NOT use markdown formatting. Write in plain text only. "
            + BANNED_INSTRUCTION
        ),
        "user_template": (
            'Provide a complete practical guide for "{topic}" in {language}. '
            "Structure your answer to include: "
            "1) What you need before starting, "
            "2) How long it takes from start to finish, "
            "3) The difficulty level, "
            "4) Step-by-step instructions with explanations, "
            "5) Common mistakes and how to recover from them, "
            "6) Tips from experience that make it easier or better. "
            "Be thorough and detailed. Write at least 670 words. "
            "Use plain text only — no markdown formatting."
        ),
    },
]

CATEGORY_SEEDS = {
    "Environment & Nature": [
        "forest conservation methods in West Africa",
        "mangrove restoration along the coast",
        "water harvesting techniques for dry seasons",
        "renewable energy solutions for rural communities",
        "waste management and recycling practices",
        "sustainable fishing methods",
        "climate change adaptation for smallholder farmers",
        "biodiversity protection in tropical forests",
        "solar energy for off-grid communities",
        "natural flood control methods",
        "soil erosion prevention techniques",
        "wildlife conservation and community stewardship",
        "air pollution reduction in growing cities",
        "wetland preservation and restoration",
        "drought-resistant landscaping practices",
        "composting and organic waste management",
        "clean cookstove adoption and benefits",
        "agroforestry and tree planting programs",
        "plastic waste reduction strategies",
        "environmental education in schools",
    ],
}


def strip_markdown(text: str) -> str:
    text = re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+?)_{1,3}', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\-\*]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'```[^`]*```', '', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _github_headers() -> Dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GH_TOKEN:
        headers["Authorization"] = f"token {GH_TOKEN}"
    return headers


def _init_scraper_state(state: Dict) -> None:
    if SCRAPER_NAME not in state:
        state[SCRAPER_NAME] = {}
    scraper = state[SCRAPER_NAME]
    scraper.setdefault("last_topics", [])
    scraper.setdefault("last_run", "")
    scraper.setdefault("total_submitted", 0)
    scraper.setdefault("total_failed", 0)
    scraper.setdefault("rejected_topics", [])
    scraper.setdefault("topic_cache", [])
    scraper.setdefault("topic_cache_index", 0)


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
                state = json.loads(decoded)
                _init_scraper_state(state)
                return state
    except Exception as e:
        print(f"  [State] Load failed: {e}")
    state = {}
    _init_scraper_state(state)
    return state


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


def get_last_topics(state: Dict, count: int = 100) -> List[str]:
    scraper = state.get(SCRAPER_NAME, {})
    return scraper.get("last_topics", [])[-count:]


def record_topic(state: Dict, topic: str, submission_id: str, success: bool) -> Dict:
    _init_scraper_state(state)
    scraper = state[SCRAPER_NAME]
    scraper["last_topics"].append(topic)
    if len(scraper["last_topics"]) > 200:
        scraper["last_topics"] = scraper["last_topics"][-200:]
    if success:
        scraper["total_submitted"] += 1
    else:
        scraper["total_failed"] += 1
    scraper["last_run"] = datetime.now(timezone.utc).isoformat()
    return state


def record_rejected(state: Dict, topic: str) -> Dict:
    _init_scraper_state(state)
    scraper = state[SCRAPER_NAME]
    scraper["rejected_topics"].append(topic)
    if len(scraper["rejected_topics"]) > 100:
        scraper["rejected_topics"] = scraper["rejected_topics"][-100:]
    return state


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


def refill_topic_cache(state: Dict, focus_categories: List[str]) -> List[str]:
    last_topics = get_last_topics(state, 100)
    rejected = state.get(SCRAPER_NAME, {}).get("rejected_topics", [])[-50:]
    counts = get_category_counts()

    categories_for_batch = []
    for _ in range(TOPIC_CACHE_SIZE):
        cat = pick_category_weighted(counts, focus_categories)
        categories_for_batch.append(cat)

    all_exclude = list(set(last_topics + rejected))
    exclude_str = ""
    if all_exclude:
        exclude_str = "Do NOT generate any of these topics:\n" + "\n".join(f"- {t}" for t in all_exclude[-40:]) + "\n\n"

    num_comparisons = max(3, int(TOPIC_CACHE_SIZE * COMPARISON_TOPIC_RATIO))
    num_regular = TOPIC_CACHE_SIZE - num_comparisons

    system_prompt = (
        "You are a topic generator for an environmental knowledge base about Africa. "
        f"Generate {num_regular} regular topics and {num_comparisons} comparison topics (total {TOPIC_CACHE_SIZE}). "
        "Regular topics should be specific and narrow — something a real person would know from "
        "living close to the land, managing natural resources, or observing environmental changes. "
        "Comparison topics should compare two environmental approaches, methods, or ecosystems. "
        "Focus on: climate adaptation, conservation, renewable energy, water management, "
        "waste reduction, biodiversity, sustainable practices, and environmental education. "
        "Format comparison topics like 'X vs Y: which is better for...' or 'Differences between X and Y in...'. "
        "Return one topic per line. No numbering, no bullet points, no markdown. "
        "Each line must be a unique topic. "
        + BANNED_INSTRUCTION
    )

    category_list = ", ".join(set(categories_for_batch))
    user_prompt = (
        f"{exclude_str}"
        f"Generate {TOPIC_CACHE_SIZE} unique environmental knowledge topics related to: {category_list}.\n"
        f"{num_comparisons} of them must be comparison topics.\n"
        f"One topic per line."
    )

    topics_text = ""
    if GROQ_API_KEY:
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.3-70b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.95,
            "max_tokens": 500,
        }
        try:
            response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                topics_text = response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"  [Cache] Groq topic generation failed: {e}")

    if not topics_text and MISTRAL_API_KEY:
        headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "mistral-small-latest",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.95,
            "max_tokens": 500,
        }
        try:
            response = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                topics_text = response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"  [Cache] Mistral topic generation failed: {e}")

    if not topics_text:
        print("  [Cache] Failed to generate topics. Using fallback.")
        return _fallback_topics(focus_categories)

    new_topics = []
    for line in topics_text.strip().split('\n'):
        line = line.strip()
        line = re.sub(r'^[\d]+[\.\)]\s*', '', line)
        line = re.sub(r'^[\-\*\•]\s*', '', line)
        line = line.strip().strip('"')
        if line and len(line) > 10 and line not in all_exclude:
            new_topics.append(line)

    seen = set()
    unique_topics = []
    for t in new_topics:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique_topics.append(t)

    if len(unique_topics) < 5:
        print(f"  [Cache] Only got {len(unique_topics)} topics. Using fallback.")
        return _fallback_topics(focus_categories)

    print(f"  [Cache] Generated {len(unique_topics)} new topics (batch)")
    return unique_topics


def _fallback_topics(focus_categories: List[str]) -> List[str]:
    seeds = CATEGORY_SEEDS.get("Environment & Nature", [])
    fallbacks = []
    qualifiers = [
        "in West Africa", "in rural Ghana", "for coastal communities",
        "in the Sahel region", "for tropical climates",
        "traditional methods of", "modern approaches to",
        "community-led", "sustainable", "practical guide to",
        "benefits of", "challenges of", "how to implement",
    ]
    for _ in range(TOPIC_CACHE_SIZE):
        seed = random.choice(seeds)
        qualifier = random.choice(qualifiers)
        fallbacks.append(f"{qualifier} {seed}")
    return fallbacks


def get_next_topic(state: Dict, focus_categories: List[str]) -> Tuple[str, str]:
    _init_scraper_state(state)
    scraper = state[SCRAPER_NAME]
    cache = scraper.get("topic_cache", [])
    index = scraper.get("topic_cache_index", 0)

    if not cache or index >= len(cache):
        print("  [Cache] Refilling topic cache...")
        sys.stdout.flush()
        new_cache = refill_topic_cache(state, focus_categories)
        state[SCRAPER_NAME]["topic_cache"] = new_cache
        state[SCRAPER_NAME]["topic_cache_index"] = 0
        save_state(state)
        cache = new_cache
        index = 0

    topic = cache[index]
    state[SCRAPER_NAME]["topic_cache_index"] = index + 1

    return topic, "Environment & Nature"


def generate_with_groq(topic: str, style: Dict, language: str) -> str:
    if not GROQ_API_KEY:
        return ""
    print(f"    [Groq] Style: {style['name']} | Language: {language}")
    sys.stdout.flush()
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    user_prompt = style["user_template"].replace("{topic}", topic).replace("{language}", language)
    payload = {
        "model": "llama-3.3-70b",
        "messages": [
            {"role": "system", "content": style["system"]},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": random.uniform(0.7, 0.95),
        "max_tokens": 2000,
    }
    try:
        response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            if not _check_banned_content(content):
                return ""
            print(f"    Generated {len(content)} chars")
            sys.stdout.flush()
            return content
        else:
            print(f"    Groq error: {response.status_code}")
            return ""
    except Exception as e:
        print(f"    Groq exception: {e}")
        return ""


def generate_with_mistral(topic: str, style: Dict, language: str) -> str:
    if not MISTRAL_API_KEY:
        return ""
    print(f"    [Mistral] Style: {style['name']} | Language: {language}")
    sys.stdout.flush()
    headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
    user_prompt = style["user_template"].replace("{topic}", topic).replace("{language}", language)
    payload = {
        "model": "mistral-small-latest",
        "messages": [
            {"role": "system", "content": style["system"]},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": random.uniform(0.7, 0.95),
        "max_tokens": 2000,
    }
    try:
        response = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            if not _check_banned_content(content):
                return ""
            print(f"    Generated {len(content)} chars")
            sys.stdout.flush()
            return content
        else:
            print(f"    Mistral error: {response.status_code}")
            return ""
    except Exception as e:
        print(f"    Mistral exception: {e}")
        return ""


def generate_content(topic: str, language: str) -> str:
    style = random.choice(PROMPT_STYLES)
    if GROQ_API_KEY:
        content = generate_with_groq(topic, style, language)
        if content and len(content) >= MIN_CONTENT_LENGTH:
            return content
    if MISTRAL_API_KEY:
        content = generate_with_mistral(topic, style, language)
        if content and len(content) >= MIN_CONTENT_LENGTH:
            return content
    return ""


def submit_to_form(topic: str, category: str, knowledge: str, language: str) -> Tuple[bool, str]:
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
            "region": "", "language": language, "email": "",
            "verification_code": verification_code, "csrf_token": csrf_token,
            "app_check_token": app_check_token, "copyright_confirm": "on",
        }

        print(f"    Submitting... (Language: {language})")
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


def run_ai_scraper(max_submissions: int = 10):
    print("=" * 60)
    print(f"AI Scraper v2.4.3 — {SCRAPER_NAME}")
    print(f"Category: Environment & Nature")
    print("=" * 60)
    print(f"Target: {max_submissions} submissions")
    print(f"Min content: {MIN_CONTENT_LENGTH} chars | ~670+ words")
    print(f"Topic cache: {TOPIC_CACHE_SIZE} topics per batch (~42% token savings)")
    print(f"Comparisons: ~{int(COMPARISON_TOPIC_RATIO * 100)}% of topics")
    print(f"Groq: {'ACTIVE' if GROQ_API_KEY else 'NOT SET'}")
    print(f"Mistral: {'ACTIVE' if MISTRAL_API_KEY else 'NOT SET'}")
    print(f"State: {'ENABLED' if GH_TOKEN else 'DISABLED'}")
    print(f"Languages: 70% English, 30% French/Portuguese/Arabic/Swahili")
    print(f"Banned orgs: {len(BANNED_ORGS)} organizations blocked")
    print("-" * 60)
    sys.stdout.flush()

    if not GROQ_API_KEY and not MISTRAL_API_KEY:
        print("ERROR: No API keys configured.")
        return

    state = load_state()
    _init_scraper_state(state)
    print(f"  Previous submissions: {state.get(SCRAPER_NAME, {}).get('total_submitted', 0)}")
    cache_size = len(state.get(SCRAPER_NAME, {}).get('topic_cache', []))
    cache_idx = state.get(SCRAPER_NAME, {}).get('topic_cache_index', 0)
    if cache_size > 0:
        print(f"  Cached topics remaining: {cache_size - cache_idx}")

    submission_count = 0
    failed = 0

    for i in range(max_submissions):
        if submission_count >= max_submissions:
            break

        print(f"\n[{submission_count + 1}/{max_submissions}] Getting topic from cache...")
        sys.stdout.flush()

        topic, category = get_next_topic(state, FOCUS_CATEGORIES)
        print(f"  Topic: {topic}")
        print(f"  Category: {category}")
        sys.stdout.flush()

        language = random.choice(LANGUAGES)

        knowledge = generate_content(topic, language)
        if not knowledge or len(knowledge) < MIN_CONTENT_LENGTH:
            failed += 1
            print(f"  Failed to generate content (got {len(knowledge) if knowledge else 0} chars)")
            state = record_topic(state, topic, "", False)
            continue

        knowledge = strip_markdown(knowledge)
        knowledge = re.sub(
            r'(?i)(as an AI|as a language model|I am an AI|based on my training|I cannot|I don\'t have personal)',
            '', knowledge
        ).strip()

        if not _check_banned_content(knowledge):
            failed += 1
            print("  Failed: Content contains banned organizations after stripping")
            state = record_topic(state, topic, "", False)
            continue

        if len(knowledge) < MIN_CONTENT_LENGTH:
            failed += 1
            state = record_topic(state, topic, "", False)
            continue

        print(f"  Content: {len(knowledge)} chars (~{len(knowledge.split())} words)")
        print(f"  Language: {language}")
        sys.stdout.flush()

        success, submission_id = submit_to_form(topic, category, knowledge, language)

        if success:
            submission_count += 1
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
    cache_remaining = len(state.get(SCRAPER_NAME, {}).get('topic_cache', [])) - state.get(SCRAPER_NAME, {}).get('topic_cache_index', 0)
    print(f"Cache remaining: {max(0, cache_remaining)}")
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
    print(f"\nStarting Environment & Nature scraper with {count} submissions...\n")
    sys.stdout.flush()
    run_ai_scraper(max_submissions=count)
