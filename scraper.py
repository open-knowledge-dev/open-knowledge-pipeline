"""
Web Knowledge Scraper — v2.3
=============================
Searches public domain sources for knowledge content with:
- Wikipedia as primary source (most relevant)
- StackExchange for tech topics only
- MDN for web development topics only
- Relevance gate — skips content not matching the topic
- Higher length requirements for quality
- State file memory to avoid repeating URLs and topics
- Category awareness toward thin categories
- Multiple rewrite styles for variety
- Region rotation across African countries
- Language variation (70% English, 30% French/Portuguese/Arabic/Swahili)

Sources: Wikipedia, StackExchange, MDN Web Docs
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
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
SUBMISSIONS_PER_RUN = int(os.getenv("SUBMISSIONS_PER_RUN", "10"))
SUBMISSION_DELAY = int(os.getenv("SUBMISSION_DELAY", "30"))
REQUEST_TIMEOUT = 30

GH_TOKEN = os.getenv("GH_TOKEN", "")
KNOWLEDGE_REPO = os.getenv("KNOWLEDGE_REPO", "")
GITHUB_API = "https://api.github.com"

FOCUS_CATEGORIES_RAW = os.getenv("FOCUS_CATEGORIES", "")
FOCUS_CATEGORIES = [c.strip() for c in FOCUS_CATEGORIES_RAW.split(",") if c.strip()]

SCRAPER_NAME = os.getenv("SCRAPER_NAME", "web-scraper")
STATE_FILE_PATH = "admin/scraper-state.json"

MIN_SCRAPED_LENGTH = 500
MIN_REWRITTEN_LENGTH = 350

# ===========================================================================
# Region Rotation
# ===========================================================================

AFRICAN_REGIONS = [
    "Greater Accra, Ghana", "Kumasi, Ghana", "Cape Coast, Ghana",
    "Tamale, Ghana", "Lagos, Nigeria", "Abuja, Nigeria",
    "Kano, Nigeria", "Nairobi, Kenya", "Mombasa, Kenya",
    "Kisumu, Kenya", "Cape Town, South Africa", "Johannesburg, South Africa",
    "Durban, South Africa", "Dar es Salaam, Tanzania", "Arusha, Tanzania",
    "Kigali, Rwanda", "Addis Ababa, Ethiopia", "Kampala, Uganda",
    "Abidjan, Cote d'Ivoire", "Dakar, Senegal", "Bamako, Mali",
    "Ouagadougou, Burkina Faso", "Cotonou, Benin", "Lome, Togo",
    "Accra, Ghana", "Freetown, Sierra Leone", "Monrovia, Liberia",
    "Banjul, Gambia", "Conakry, Guinea", "Niamey, Niger",
    "Yaounde, Cameroon", "Douala, Cameroon", "Luanda, Angola",
    "Maputo, Mozambique", "Lusaka, Zambia", "Harare, Zimbabwe",
    "Gaborone, Botswana", "Windhoek, Namibia", "Lilongwe, Malawi",
    "Kinshasa, DR Congo", "Khartoum, Sudan", "Juba, South Sudan",
    "Asmara, Eritrea", "Mogadishu, Somalia", "Praia, Cape Verde",
]

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

ALL_CATEGORIES = [
    "Agriculture & Farming", "Business & Finance", "Culture & Traditions",
    "Education & Learning", "Health & Medicine", "Technology & Innovation",
    "Tourism & Travel", "History & Heritage", "Food & Cuisine",
    "Music & Dance", "Language & Proverbs", "Religion & Spirituality",
    "Sports & Games", "Fashion & Textiles", "Environment & Nature",
    "Governance & Leadership", "Family & Relationships", "Arts & Crafts",
    "Science & Innovation", "Other",
]

CATEGORY_SEEDS = {
    "Agriculture & Farming": [
        "small-scale farming techniques", "crop rotation methods", "natural pest control",
        "water conservation farming", "soil fertility management", "livestock care",
        "seed saving practices", "harvest storage methods", "agroforestry",
        "urban farming techniques",
    ],
    "Culture & Traditions": [
        "traditional ceremonies", "oral storytelling", "community festivals",
        "traditional clothing", "coming of age rituals", "wedding customs",
        "naming ceremonies", "funeral traditions", "harvest celebrations",
        "dance traditions",
    ],
    "Health & Medicine": [
        "herbal remedies", "traditional healing", "nutrition practices",
        "maternal health", "childhood illnesses", "preventive care",
        "mental wellness", "first aid knowledge", "community health",
        "medicinal plants",
    ],
    "Food & Cuisine": [
        "traditional recipes", "food preservation", "fermentation methods",
        "staple food preparation", "spice blending", "street food culture",
        "ceremonial foods", "cooking techniques", "beverage preparation",
        "food safety practices",
    ],
    "Education & Learning": [
        "study techniques", "teaching methods", "apprenticeship systems",
        "language learning", "vocational training", "adult education",
        "child education", "skill sharing", "memory techniques",
        "practical education",
    ],
    "History & Heritage": [
        "pre-colonial kingdoms", "trade routes", "independence movements",
        "archaeological sites", "oral histories", "historical figures",
        "colonial resistance", "traditional governance", "cultural heritage",
        "ancient civilizations",
    ],
    "Technology & Innovation": [
        "mobile technology", "renewable energy", "local innovations",
        "digital skills", "appropriate technology", "solar solutions",
        "tech education", "innovation hubs", "tech for agriculture",
        "mobile money systems",
    ],
    "Business & Finance": [
        "small business tips", "market trading", "savings groups",
        "cooperative business", "financial literacy", "entrepreneurship",
        "local manufacturing", "import export", "business planning",
        "customer service",
    ],
    "Environment & Nature": [
        "forest conservation", "water management", "wildlife protection",
        "climate adaptation", "sustainable practices", "renewable resources",
        "waste management", "land restoration", "coastal protection",
        "biodiversity",
    ],
    "Music & Dance": [
        "traditional instruments", "dance styles", "musical traditions",
        "drumming patterns", "ceremonial music", "folk songs",
        "music education", "dance costumes", "modern fusion music",
        "music production",
    ],
    "Sports & Games": [
        "traditional games", "wrestling traditions", "board games",
        "children's games", "sports history", "running traditions",
        "community sports", "school sports", "indigenous games",
        "modern athletics",
    ],
    "Language & Proverbs": [
        "proverb meanings", "language preservation", "greeting customs",
        "oral traditions", "naming practices", "communication styles",
        "poetry forms", "storytelling language", "indigenous languages",
        "wisdom sayings",
    ],
    "Religion & Spirituality": [
        "traditional beliefs", "religious practices", "sacred sites",
        "spiritual healing", "festival celebrations", "ancestral veneration",
        "divination practices", "religious tolerance", "creation stories",
        "moral teachings",
    ],
    "Arts & Crafts": [
        "weaving techniques", "pottery making", "wood carving",
        "basket weaving", "jewelry making", "textile design",
        "mask carving", "metalworking", "beadwork", "leather craft",
    ],
    "Fashion & Textiles": [
        "fabric dyeing", "weaving patterns", "traditional dress",
        "textile history", "clothing customs", "fashion design",
        "headwrap styles", "embroidery", "batik making", "kente weaving",
    ],
    "Tourism & Travel": [
        "historical sites", "natural attractions", "cultural festivals",
        "eco-tourism", "travel tips", "local guides", "heritage sites",
        "market visits", "adventure travel", "community tourism",
    ],
    "Governance & Leadership": [
        "traditional leadership", "community organizing", "conflict resolution",
        "chieftaincy systems", "local governance", "women in leadership",
        "youth participation", "consensus building", "justice systems",
        "public participation",
    ],
    "Family & Relationships": [
        "parenting practices", "marriage customs", "elder care",
        "family structures", "child upbringing", "community support",
        "conflict mediation", "relationship advice", "family values",
        "intergenerational knowledge",
    ],
    "Science & Innovation": [
        "indigenous knowledge", "local inventions", "traditional astronomy",
        "natural mathematics", "weather prediction", "engineering techniques",
        "agricultural science", "medical innovations", "water technology",
        "energy solutions",
    ],
}


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


def get_scraped_urls(state: Dict) -> List[str]:
    return state.get(SCRAPER_NAME, {}).get("scraped_urls", [])


def record_submission(state: Dict, topic: str, url: str, success: bool) -> Dict:
    if SCRAPER_NAME not in state:
        state[SCRAPER_NAME] = {
            "last_topics": [], "scraped_urls": [], "last_run": "",
            "total_submitted": 0, "total_failed": 0,
        }
    scraper = state[SCRAPER_NAME]
    scraper["last_topics"].append(topic)
    if len(scraper["last_topics"]) > 100:
        scraper["last_topics"] = scraper["last_topics"][-100:]
    if url and url not in scraper.setdefault("scraped_urls", []):
        scraper["scraped_urls"].append(url)
    if len(scraper.get("scraped_urls", [])) > 200:
        scraper["scraped_urls"] = scraper["scraped_urls"][-200:]
    if success:
        scraper["total_submitted"] = scraper.get("total_submitted", 0) + 1
    else:
        scraper["total_failed"] = scraper.get("total_failed", 0) + 1
    scraper["last_run"] = datetime.now(timezone.utc).isoformat()
    return state


# ===========================================================================
# Category and Topic Selection
# ===========================================================================

def pick_category() -> str:
    if FOCUS_CATEGORIES:
        return random.choice(FOCUS_CATEGORIES)
    return random.choice(ALL_CATEGORIES)


def pick_topic_for_category(category: str, state: Dict) -> str:
    seeds = CATEGORY_SEEDS.get(category, ["general knowledge"])
    last_topics = get_last_topics(state, 30)
    qualifiers = [
        "in rural communities", "in urban areas", "across West Africa",
        "in East Africa", "traditional methods of", "modern approaches to",
        "sustainable", "community-based", "practical guide to",
        "history of", "cultural significance of", "step-by-step",
        "common mistakes in", "benefits of", "challenges of",
    ]
    for seed in random.sample(seeds, len(seeds)):
        if seed not in last_topics:
            qualifier = random.choice(qualifiers)
            return f"{qualifier} {seed}"
    return f"{random.choice(qualifiers)} {random.choice(seeds)}"


# ===========================================================================
# Topic Relevance Check
# ===========================================================================

def is_content_relevant(topic: str, content: str) -> bool:
    stop_words = {
        "the", "and", "for", "with", "that", "this", "from", "are", "was",
        "have", "has", "had", "not", "but", "its", "can", "all", "will",
        "about", "which", "their", "what", "when", "where", "who", "how",
        "across", "into", "over", "after", "before", "between", "under",
        "east", "west", "north", "south", "africa", "african",
        "in", "of", "to", "a", "an", "is", "it", "on", "by", "as", "at",
        "be", "or", "we", "our", "these", "those", "they", "them",
    }
    topic_words = [
        w.lower() for w in re.findall(r'[a-zA-Z]{3,}', topic)
        if w.lower() not in stop_words
    ]
    if not topic_words:
        return True
    content_lower = content.lower()
    matches = sum(1 for w in topic_words if w in content_lower)
    threshold = max(2, len(topic_words) // 2)
    return matches >= threshold


# ===========================================================================
# Web Sources
# ===========================================================================

def search_wikipedia(topic: str) -> Optional[Tuple[str, str]]:
    print(f"    [Wikipedia] {topic[:60]}...")
    sys.stdout.flush()
    try:
        search_url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query", "list": "search", "srsearch": topic,
            "format": "json", "srlimit": 3,
        }
        headers = {"User-Agent": "KnowledgePipeline/2.3"}
        response = requests.get(search_url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        data = response.json()
        results = data.get("query", {}).get("search", [])
        if not results:
            return None
        for result in results[:3]:
            page_title = result["title"]
            extract_params = {
                "action": "query", "prop": "extracts", "exintro": False,
                "explaintext": True, "titles": page_title, "format": "json",
            }
            response = requests.get(search_url, params=extract_params, headers=headers, timeout=REQUEST_TIMEOUT)
            data = response.json()
            pages = data.get("query", {}).get("pages", {})
            for page_data in pages.values():
                extract = page_data.get("extract", "")
                if extract and len(extract) >= MIN_SCRAPED_LENGTH:
                    if is_content_relevant(topic, extract):
                        url = f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}"
                        print(f"    Got {len(extract)} chars — relevant")
                        sys.stdout.flush()
                        return extract[:5000], url
        return None
    except Exception as e:
        print(f"    Wikipedia error: {e}")
        return None


def search_stackexchange(topic: str) -> Optional[Tuple[str, str]]:
    tech_keywords = [
        "programming", "code", "software", "developer", "web", "app",
        "database", "server", "API", "framework", "JavaScript", "Python",
        "Java", "PHP", "Ruby", "HTML", "CSS", "SQL", "C++", "C#",
        "security", "deployment", "testing", "debugging", "algorithm",
        "mobile", "cloud", "devops", "frontend", "backend", "fullstack",
        "react", "angular", "vue", "node", "docker", "kubernetes",
        "linux", "git", "open source",
    ]
    if not any(kw.lower() in topic.lower() for kw in tech_keywords):
        return None
    print(f"    [StackExchange] {topic[:60]}...")
    sys.stdout.flush()
    try:
        search_url = "https://api.stackexchange.com/2.3/search/advanced"
        params = {
            "order": "desc", "sort": "votes", "q": topic,
            "site": "stackoverflow", "pagesize": 1, "filter": "withbody",
        }
        headers = {"User-Agent": "KnowledgePipeline/2.3"}
        response = requests.get(search_url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            return None
        items = response.json().get("items", [])
        if not items:
            return None
        item = items[0]
        title = item.get("title", "")
        body = re.sub(r'<[^>]+>', ' ', item.get("body", ""))
        body = re.sub(r'\s+', ' ', body).strip()
        combined = f"{title}. {body[:1500]}"
        if len(combined) >= MIN_SCRAPED_LENGTH and is_content_relevant(topic, combined):
            url = item.get("link", "")
            print(f"    Got {len(combined)} chars — relevant")
            sys.stdout.flush()
            return combined[:5000], url
        return None
    except Exception as e:
        print(f"    StackExchange error: {e}")
        return None


def search_mdn(topic: str) -> Optional[Tuple[str, str]]:
    web_keywords = [
        "HTML", "CSS", "JavaScript", "DOM", "accessibility", "responsive",
        "Flexbox", "Grid", "animation", "transition", "event", "fetch",
        "API", "web", "browser", "frontend", "stylesheet", "selector",
        "element", "attribute", "property", "method", "function",
        "array", "object", "promise", "async", "component",
    ]
    if not any(kw.lower() in topic.lower() for kw in web_keywords):
        return None
    print(f"    [MDN] {topic[:60]}...")
    sys.stdout.flush()
    try:
        search_url = "https://developer.mozilla.org/api/v1/search"
        params = {"q": topic, "locale": "en-US"}
        headers = {"User-Agent": "KnowledgePipeline/2.3"}
        response = requests.get(search_url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            return None
        documents = response.json().get("documents", [])
        if not documents:
            return None
        doc = documents[0]
        combined = f"{doc.get('title', '')}. {doc.get('summary', '')}"
        if len(combined) >= MIN_SCRAPED_LENGTH and is_content_relevant(topic, combined):
            url = f"https://developer.mozilla.org{doc.get('mdn_url', '')}"
            print(f"    Got {len(combined)} chars — relevant")
            sys.stdout.flush()
            return combined[:5000], url
        return None
    except Exception as e:
        print(f"    MDN error: {e}")
        return None


def fetch_content(topic: str, category: str, state: Dict) -> Optional[Tuple[str, str]]:
    scraped_urls = get_scraped_urls(state)
    result = search_wikipedia(topic)
    if result:
        content, url = result
        if url not in scraped_urls:
            return content, url
    if category in ["Technology & Innovation", "Science & Innovation", "Education & Learning"]:
        result = search_stackexchange(topic)
        if result:
            content, url = result
            if url not in scraped_urls:
                return content, url
    result = search_mdn(topic)
    if result:
        content, url = result
        if url not in scraped_urls:
            return content, url
    return None


# ===========================================================================
# Content Rewriting
# ===========================================================================

def rewrite_content(original: str, topic: str, category: str) -> str:
    if len(original) < MIN_SCRAPED_LENGTH:
        return ""
    personal_starters = [
        "In my community, we", "Growing up, I learned that",
        "My grandmother taught me that", "Many people in our region believe",
        "From my experience,", "Elders in our area say",
        "I remember my father telling me", "In our tradition,",
        "Local farmers have always known", "Through generations, we have",
        "My mentor once told me", "I've seen with my own eyes how",
        "People in my village say", "The old way of doing things",
        "What I know about this is", "I learned this the hard way:",
        "A wise person once told me", "In the market, everyone knows",
        "Our ancestors passed down this knowledge:",
        "If you ask any elder, they'll tell you",
        "Through trial and error, I discovered",
        "The secret that nobody tells you is",
        "Here in our part of the world, we",
        "My uncle who has done this for 40 years says",
        "The difference between success and failure is",
        "What most people don't understand is",
        "I wish someone had told me earlier that",
        "After years of doing this, I can say",
        "The real trick to making this work is",
        "Nobody teaches you this in school, but",
    ]
    conclusions = [
        "This knowledge has been passed down through generations.",
        "I share this because it's important for the next generation.",
        "This is what works for us. I hope it helps others too.",
        "I hope this knowledge helps someone else.",
        "That's the wisdom I've gathered over the years.",
        "May this knowledge serve you well.",
        "These are lessons learned from real life, not books.",
        "I'm sharing this so the knowledge doesn't get lost.",
        "The old ways have wisdom that modern life forgets.",
        "Take this advice and make it your own.",
    ]
    starter = random.choice(personal_starters)
    sentences = re.split(r'(?<=[.!?])\s+', original)
    key_sentences = [s.strip() for s in sentences if 30 < len(s.strip()) < 500]
    if not key_sentences:
        return ""
    max_sentences = min(len(key_sentences), 12)
    style = random.choice(["narrative", "instructional", "comparative"])
    if style == "narrative":
        rewritten = f"{starter} {key_sentences[0].lower()}\n\n"
        for sentence in key_sentences[1:max_sentences]:
            rewritten += f"{sentence}\n\n"
    elif style == "instructional":
        rewritten = f"{starter}\n\n"
        for i, sentence in enumerate(key_sentences[:max_sentences], 1):
            rewritten += f"{i}. {sentence}\n\n"
    else:
        rewritten = f"{starter} {key_sentences[0].lower()}\n\n"
        if len(key_sentences) >= 3:
            rewritten += f"On one hand, {key_sentences[1].lower()}\n\n"
            rewritten += f"On the other hand, {key_sentences[min(2, len(key_sentences)-1)].lower()}\n\n"
        for sentence in key_sentences[3:max_sentences]:
            rewritten += f"{sentence}\n\n"
    rewritten += random.choice(conclusions)
    if len(rewritten) < MIN_REWRITTEN_LENGTH:
        rewritten += "\n\nThis is knowledge that matters in daily life. I am sharing what I know so others can benefit from it. What I have learned comes from real experience, not from books or the internet."
    return rewritten[:50000]


# ===========================================================================
# Submission
# ===========================================================================

def submit_to_form(topic: str, category: str, knowledge: str, language: str, region: str) -> Tuple[bool, str]:
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
        app_check_token = SCRAPER_API_KEY if SCRAPER_API_KEY else ""
        submit_data = {
            "topic": topic, "category": category, "knowledge": knowledge,
            "region": region, "language": language, "email": "",
            "verification_code": verification_code, "csrf_token": csrf_token,
            "app_check_token": app_check_token, "copyright_confirm": "on",
        }
        print(f"    Submitting... (Region: {region}, Language: {language})")
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

def run_scraper(max_submissions: int = 10):
    print("=" * 60)
    print(f"Web Scraper v2.3 — {SCRAPER_NAME}")
    print("=" * 60)
    print(f"Target: {max_submissions} submissions")
    print(f"Focus: {FOCUS_CATEGORIES if FOCUS_CATEGORIES else 'All categories'}")
    print(f"Min source: {MIN_SCRAPED_LENGTH} chars | Min rewrite: {MIN_REWRITTEN_LENGTH} chars")
    print(f"State: {'ENABLED' if GH_TOKEN else 'DISABLED'}")
    print(f"Regions: Rotating across {len(AFRICAN_REGIONS)} African locations")
    print(f"Languages: 70% English, 30% French/Portuguese/Arabic/Swahili")
    print("-" * 60)
    sys.stdout.flush()

    state = load_state()
    print(f"  Previous submissions: {state.get(SCRAPER_NAME, {}).get('total_submitted', 0)}")

    submission_count = 0
    skipped = 0
    failed = 0
    max_attempts = max_submissions * 4

    for i in range(max_attempts):
        if submission_count >= max_submissions:
            break
        print(f"\n[{submission_count + 1}/{max_submissions}] Selecting topic...")
        sys.stdout.flush()
        category = pick_category()
        topic = pick_topic_for_category(category, state)
        print(f"  Topic: {topic}")
        print(f"  Category: {category}")
        sys.stdout.flush()
        result = fetch_content(topic, category, state)
        if not result:
            skipped += 1
            print(f"  No relevant content found, skipping")
            continue
        original_text, source_url = result
        if len(original_text) < MIN_SCRAPED_LENGTH:
            skipped += 1
            print(f"  Content too short ({len(original_text)} chars < {MIN_SCRAPED_LENGTH}), skipping")
            continue
        rewritten = rewrite_content(original_text, topic, category)
        if len(rewritten) < MIN_REWRITTEN_LENGTH:
            skipped += 1
            print(f"  Rewrite too short ({len(rewritten)} chars < {MIN_REWRITTEN_LENGTH}), skipping")
            continue
        # Pick random region and language
        region = random.choice(AFRICAN_REGIONS)
        language = random.choice(LANGUAGES)
        print(f"  Content: {len(rewritten)} chars")
        print(f"  Region: {region} | Language: {language}")
        sys.stdout.flush()
        success, submission_id = submit_to_form(topic, category, rewritten, language, region)
        if success:
            submission_count += 1
            state = record_submission(state, topic, source_url, True)
        else:
            failed += 1
            state = record_submission(state, topic, source_url, False)
        if GH_TOKEN:
            save_state(state)
        if submission_count < max_submissions:
            wait_time = SUBMISSION_DELAY + random.randint(1, 15)
            print(f"  Waiting {wait_time}s...")
            sys.stdout.flush()
            time.sleep(wait_time)

    print("\n" + "=" * 60)
    print(f"Done: {submission_count} submitted | {skipped} skipped | {failed} failed")
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
    print(f"\nStarting web scraper with {count} submissions...\n")
    sys.stdout.flush()
    run_scraper(max_submissions=count)
