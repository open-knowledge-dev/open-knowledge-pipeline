"""
Book Processor — v5.0.0
=======================
Automatically downloads public domain books from Project Gutenberg,
extracts text, splits into chunks, rewrites via Cloudflare Qwen models in
conversational African voice, and submits to the training form.

New in v5.0.0:
- Human voice validation (no AI words, no markdown, max 20-word sentences)
- Aggressive markdown stripping
- Retry logic (3 attempts) on validation failure
- Validation failures logged to admin/validation-failures.jsonl
- Simple vocabulary (10-year-old level with explanations)
- Clean models only — NO Llama/Meta

All books are pre-1927 — indisputably public domain.
Zero copyright risk. Fully automated.

Schedule: Runs daily. Processes one book per run.
Resumes from where it left off if interrupted.
"""

import os
import sys
import time
import random
import json
import base64
import re
import requests
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict

# Import human voice checker
try:
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
    METADATA_AVAILABLE = False
    print("[WARNING] scraper_metadata.py not found. Metadata logging disabled.")


# ===========================================================================
# Configuration
# ===========================================================================

TRAINING_FORM_URL = os.getenv("TRAINING_FORM_URL", "")

# Cloudflare AI credentials
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_MODEL = os.getenv("CLOUDFLARE_MODEL", "@cf/qwen/qwen3-30b-a3b-fp8")

# Mistral API (fallback)
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")

SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
SUBMISSION_DELAY = int(os.getenv("SUBMISSION_DELAY", "60"))
REQUEST_TIMEOUT = 90
MAX_RETRIES = 3

GH_TOKEN = os.getenv("GH_TOKEN", "")
KNOWLEDGE_REPO = os.getenv("KNOWLEDGE_REPO", "")
GITHUB_API = "https://api.github.com"
VALIDATION_LOG_PATH = "admin/validation-failures.jsonl"

CLOUDFLARE_API_URL = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{CLOUDFLARE_MODEL}" if CLOUDFLARE_ACCOUNT_ID else ""
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

STATE_FILE_PATH = "admin/book-processor-state.json"
MAX_CHUNKS_PER_RUN = 40
MIN_CHUNK_LENGTH = 300
MIN_WORDS = 400


# ===========================================================================
# Banned Organizations
# ===========================================================================

BANNED_ORGS = [
    "FAO", "Food and Agriculture Organization",
    "WHO", "World Health Organization",
    "UN", "United Nations",
    "World Bank", "IMF", "International Monetary Fund",
    "UNDP", "UNESCO", "UNICEF",
    "USAID", "DFID", "GIZ",
    "World Food Programme", "WFP",
    "International Labour Organization", "ILO",
    "World Trade Organization", "WTO",
    "African Development Bank", "AfDB",
    "European Union", "EU"
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
# Public Domain Book List (Project Gutenberg IDs — all pre-1927)
# ===========================================================================

BOOK_LIST = [
    {"id": "1342", "title": "Pride and Prejudice", "author": "Jane Austen", "year": 1813, "category": "Culture & Traditions"},
    {"id": "2701", "title": "Moby Dick", "author": "Herman Melville", "year": 1851, "category": "Culture & Traditions"},
    {"id": "84", "title": "Frankenstein", "author": "Mary Shelley", "year": 1818, "category": "Science & Innovation"},
    {"id": "345", "title": "Dracula", "author": "Bram Stoker", "year": 1897, "category": "Culture & Traditions"},
    {"id": "1661", "title": "The Adventures of Sherlock Holmes", "author": "Arthur Conan Doyle", "year": 1892, "category": "Culture & Traditions"},
    {"id": "11", "title": "Alice's Adventures in Wonderland", "author": "Lewis Carroll", "year": 1865, "category": "Culture & Traditions"},
    {"id": "174", "title": "The Picture of Dorian Gray", "author": "Oscar Wilde", "year": 1890, "category": "Culture & Traditions"},
    {"id": "43", "title": "The Strange Case of Dr. Jekyll and Mr. Hyde", "author": "Robert Louis Stevenson", "year": 1886, "category": "Science & Innovation"},
    {"id": "1184", "title": "The Count of Monte Cristo", "author": "Alexandre Dumas", "year": 1844, "category": "Culture & Traditions"},
    {"id": "76", "title": "Adventures of Huckleberry Finn", "author": "Mark Twain", "year": 1884, "category": "Culture & Traditions"},
    {"id": "1260", "title": "Jane Eyre", "author": "Charlotte Bronte", "year": 1847, "category": "Culture & Traditions"},
    {"id": "768", "title": "Wuthering Heights", "author": "Emily Bronte", "year": 1847, "category": "Culture & Traditions"},
    {"id": "1400", "title": "Great Expectations", "author": "Charles Dickens", "year": 1861, "category": "Culture & Traditions"},
    {"id": "2600", "title": "War and Peace", "author": "Leo Tolstoy", "year": 1869, "category": "History & Heritage"},
    {"id": "4300", "title": "Ulysses", "author": "James Joyce", "year": 1922, "category": "Culture & Traditions"},
    {"id": "30254", "title": "The Souls of Black Folk", "author": "W.E.B. Du Bois", "year": 1903, "category": "History & Heritage"},
    {"id": "408", "title": "The Autobiography of an Ex-Colored Man", "author": "James Weldon Johnson", "year": 1912, "category": "Culture & Traditions"},
    {"id": "236", "title": "The Jungle Book", "author": "Rudyard Kipling", "year": 1894, "category": "Culture & Traditions"},
    {"id": "120", "title": "Treasure Island", "author": "Robert Louis Stevenson", "year": 1883, "category": "Culture & Traditions"},
    {"id": "244", "title": "A Study in Scarlet", "author": "Arthur Conan Doyle", "year": 1887, "category": "Culture & Traditions"},
    {"id": "1322", "title": "The Art of War", "author": "Sun Tzu", "year": -500, "category": "Business & Finance"},
    {"id": "2680", "title": "Meditations", "author": "Marcus Aurelius", "year": 180, "category": "Religion & Spirituality"},
    {"id": "3600", "title": "Essays of Francis Bacon", "author": "Francis Bacon", "year": 1625, "category": "Education & Learning"},
    {"id": "2160", "title": "The Prince", "author": "Niccolo Machiavelli", "year": 1532, "category": "Governance & Leadership"},
    {"id": "175", "title": "The Republic", "author": "Plato", "year": -380, "category": "Governance & Leadership"},
    {"id": "1497", "title": "Self-Reliance and Other Essays", "author": "Ralph Waldo Emerson", "year": 1841, "category": "Education & Learning"},
    {"id": "2610", "title": "Up From Slavery", "author": "Booker T. Washington", "year": 1901, "category": "History & Heritage"},
    {"id": "165", "title": "The Narrative of the Life of Frederick Douglass", "author": "Frederick Douglass", "year": 1845, "category": "History & Heritage"},
    {"id": "20228", "title": "Narrative of Sojourner Truth", "author": "Sojourner Truth", "year": 1850, "category": "History & Heritage"},
    {"id": "1228", "title": "On the Origin of Species", "author": "Charles Darwin", "year": 1859, "category": "Science & Innovation"},
]

GUTENBERG_URL = "https://www.gutenberg.org/files/{id}/{id}-0.txt"
GUTENBERG_URL_ALT = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"


# ===========================================================================
# Validation Failure Logging
# ===========================================================================

def _github_headers() -> Dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GH_TOKEN:
        headers["Authorization"] = f"token {GH_TOKEN}"
    return headers


def log_validation_failure(topic: str, category: str, reason: str, details: dict, content: str) -> None:
    if not GH_TOKEN or not KNOWLEDGE_REPO:
        return

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scraper": "book_processor",
        "model": CLOUDFLARE_MODEL if CLOUDFLARE_ACCOUNT_ID else "mistral-small-latest",
        "topic": topic,
        "category": category,
        "reason": reason,
        "details": details,
        "content_preview": content[:500] if content else "",
    }

    try:
        url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{VALIDATION_LOG_PATH}"
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

        new_line = json.dumps(entry) + "\n"
        updated_content = current_content + new_line

        payload = {
            "message": f"Log validation failure: {topic[:50]}",
            "content": base64.b64encode(updated_content.encode("utf-8")).decode("utf-8"),
            "branch": "main",
        }
        if sha:
            payload["sha"] = sha

        requests.put(url, json=payload, headers=_github_headers(), timeout=15)
    except Exception:
        pass


# ===========================================================================
# Book Download
# ===========================================================================

def download_book(book_id: str) -> Optional[str]:
    urls = [
        GUTENBERG_URL_ALT.format(id=book_id),
        GUTENBERG_URL.format(id=book_id),
    ]
    for url in urls:
        try:
            print(f"  Downloading: {url}")
            sys.stdout.flush()
            response = requests.get(url, timeout=60, headers={"User-Agent": "BookProcessor/5.0"})
            if response.status_code == 200:
                text = response.text
                text = clean_gutenberg_text(text)
                if len(text) > 10000:
                    print(f"  Downloaded {len(text)} chars")
                    return text
        except Exception as e:
            print(f"  Download error: {e}")
            continue
    return None


def clean_gutenberg_text(text: str) -> str:
    start_markers = [
        "*** START OF THE PROJECT GUTENBERG",
        "*** START OF THIS PROJECT GUTENBERG",
        "***START OF THE PROJECT GUTENBERG",
    ]
    for marker in start_markers:
        idx = text.find(marker)
        if idx != -1:
            newline = text.find("\n", idx)
            if newline != -1:
                text = text[newline + 1:]
            break

    end_markers = [
        "*** END OF THE PROJECT GUTENBERG",
        "*** END OF THIS PROJECT GUTENBERG",
        "***END OF THE PROJECT GUTENBERG",
    ]
    for marker in end_markers:
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
            break

    return text.strip()


# ===========================================================================
# Text Splitting
# ===========================================================================

def split_into_chunks(text: str, max_words: int = 700) -> List[str]:
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current_chunk = []
    current_word_count = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        word_count = len(para.split())

        if word_count < 10 and len(para) < 100:
            if current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_word_count = 0
            continue

        if current_word_count + word_count > max_words and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = [para]
            current_word_count = word_count
        else:
            current_chunk.append(para)
            current_word_count += word_count

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    chunks = [c for c in chunks if len(c.split()) >= 30]
    return chunks


# ===========================================================================
# AI Rewriting — Cloudflare (Primary)
# ===========================================================================

def rewrite_with_cloudflare(chunk: str, book_title: str, book_author: str) -> str:
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
        return ""

    system_prompt = (
        "You are a wise African storyteller sharing knowledge from classic literature. "
        "Rewrite the provided text in a warm, conversational voice that feels like "
        "an elder sharing wisdom around a fire. Keep all facts, names, dates, and "
        "key details accurate. Add practical lessons and African context where relevant. "
        "Write in first person. Write at least 400 words. "
        "Do NOT use markdown formatting — no asterisks, no hashes, no underscores. "
        "Write in plain text only. "
        "Keep every sentence under 20 words. "
        "Use only words a 10-year-old would know. "
        "If you must use a hard word, explain it right after in simple words. "
        + BANNED_INSTRUCTION
    )

    user_prompt = (
        f"This passage is from the public domain book '{book_title}' by {book_author}.\n\n"
        f"{chunk}\n\n"
        f"Rewrite this in a warm African storytelling voice. Keep the facts accurate. "
        f"Make it feel like wisdom being shared, not a book being read. "
        f"Write at least 400 words. Use plain text only. "
        f"Keep sentences short. Use simple words."
    )

    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.75,
        "max_tokens": 1500,
    }

    try:
        response = requests.post(CLOUDFLARE_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                content = data.get("result", {}).get("response", "")
                if not _check_banned_content(content):
                    return ""
                return content
        return ""
    except Exception as e:
        print(f"    Cloudflare error: {e}")
        return ""


# ===========================================================================
# AI Rewriting — Mistral (Fallback)
# ===========================================================================

def rewrite_with_mistral(chunk: str, book_title: str, book_author: str) -> str:
    if not MISTRAL_API_KEY:
        return ""

    system_prompt = (
        "You are a wise African storyteller. Rewrite this passage in a warm, "
        "conversational voice. Keep facts accurate. Add African context. "
        "Write at least 400 words. Plain text only. "
        "Keep every sentence under 20 words. "
        "Use simple words a 10-year-old would know. "
        + BANNED_INSTRUCTION
    )
    user_prompt = (
        f"From '{book_title}' by {book_author}:\n\n{chunk}\n\n"
        f"Rewrite in African storytelling voice. 400+ words. Plain text. "
        f"Keep sentences short. Use simple words."
    )

    headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "mistral-small-latest",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.75,
        "max_tokens": 1500,
    }

    try:
        response = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            if not _check_banned_content(content):
                return ""
            return content
        return ""
    except Exception as e:
        print(f"    Mistral error: {e}")
        return ""


def rewrite_chunk(chunk: str, book_title: str, book_author: str) -> Tuple[str, str]:
    """Rewrite a chunk with retry + validation. Returns (content, source)."""
    source = ""

    for attempt in range(MAX_RETRIES):
        raw = ""

        if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN:
            raw = rewrite_with_cloudflare(chunk, book_title, book_author)
            source = "cloudflare"

        if not raw and MISTRAL_API_KEY:
            raw = rewrite_with_mistral(chunk, book_title, book_author)
            source = "mistral"

        if not raw:
            continue

        cleaned = strip_markdown_symbols(raw) if VALIDATOR_AVAILABLE else raw

        if not VALIDATOR_AVAILABLE:
            if len(cleaned) >= MIN_CHUNK_LENGTH:
                return cleaned, source
            continue

        passed, details = check_human_voice(cleaned)
        if passed and len(cleaned) >= MIN_CHUNK_LENGTH:
            return cleaned, source

        print(f"    Attempt {attempt + 1} validation: {details['reasons']}")
        time.sleep(5)

    return "", source


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


# ===========================================================================
# State File (Private Knowledge Repo)
# ===========================================================================

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
    except Exception:
        pass
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
        "message": "Update book processor state",
        "content": base64.b64encode(content_json.encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha
    try:
        response = requests.put(url, json=payload, headers=_github_headers(), timeout=15)
        return response.status_code in [200, 201]
    except Exception:
        return False


# ===========================================================================
# Main
# ===========================================================================

def run_book_processor():
    print("=" * 60)
    print("Book Processor v5.0.0 — Project Gutenberg")
    print("=" * 60)
    print(f"Max chunks per run: {MAX_CHUNKS_PER_RUN}")
    print(f"Cloudflare Model: {CLOUDFLARE_MODEL}")
    print(f"Cloudflare: {'ACTIVE' if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN else 'NOT SET'}")
    print(f"Mistral: {'ACTIVE' if MISTRAL_API_KEY else 'NOT SET'} (fallback)")
    print(f"Human voice check: {'ENABLED' if VALIDATOR_AVAILABLE else 'DISABLED'}")
    print(f"Metadata: {'ENABLED' if METADATA_AVAILABLE else 'DISABLED'}")
    sys.stdout.flush()

    if not CLOUDFLARE_ACCOUNT_ID and not MISTRAL_API_KEY:
        print("ERROR: No AI providers configured.")
        return

    state = load_state()

    current_book = state.get("current_book")
    chunks = state.get("chunks", [])
    current_index = state.get("current_index", 0)
    completed_books = state.get("completed_books", [])

    if current_book and chunks and current_index < len(chunks):
        print(f"Resuming: {current_book['title']} (chunk {current_index + 1}/{len(chunks)})")
    else:
        available = [b for b in BOOK_LIST if b["id"] not in completed_books]
        if not available:
            print("All books processed! Resetting list.")
            completed_books = []
            available = BOOK_LIST

        book = random.choice(available)
        print(f"\nSelected: {book['title']} by {book['author']} ({book['year']})")
        print(f"Category: {book['category']}")
        print(f"Downloading...")
        sys.stdout.flush()

        text = download_book(book["id"])
        if not text:
            print("ERROR: Could not download book.")
            return

        chunks = split_into_chunks(text)
        print(f"Split into {len(chunks)} chunks")

        current_book = {
            "id": book["id"],
            "title": book["title"],
            "author": book["author"],
            "year": book["year"],
            "category": book["category"],
            "total_chunks": len(chunks),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        current_index = 0

        state["current_book"] = current_book
        state["chunks"] = chunks
        state["current_index"] = 0
        save_state(state)

    max_in_run = min(MAX_CHUNKS_PER_RUN, len(chunks) - current_index)
    submission_count = 0
    failed_count = 0
    validation_rejected = 0

    print(f"\nProcessing {max_in_run} chunks (of {len(chunks)} total)...")
    print("-" * 60)
    sys.stdout.flush()

    for i in range(current_index, current_index + max_in_run):
        if i >= len(chunks):
            break

        chunk = chunks[i]
        print(f"\n[{i + 1}/{len(chunks)}] Chunk {i + 1} ({len(chunk.split())} words)")

        knowledge, source = rewrite_chunk(chunk, current_book["title"], current_book["author"])
        if not knowledge:
            failed_count += 1
            print(f"  Failed to rewrite after {MAX_RETRIES} attempts")
            state["current_index"] = i + 1
            save_state(state)
            continue

        if not _check_banned_content(knowledge):
            failed_count += 1
            print(f"  Failed: banned content")
            state["current_index"] = i + 1
            save_state(state)
            continue

        if len(knowledge) < MIN_CHUNK_LENGTH:
            failed_count += 1
            print(f"  Too short ({len(knowledge)} chars)")
            state["current_index"] = i + 1
            save_state(state)
            continue

        topic = f"Wisdom from {current_book['title']} by {current_book['author']} — Part {i + 1}"
        print(f"  Topic: {topic[:80]}...")
        print(f"  Content: {len(knowledge)} chars")
        sys.stdout.flush()

        success, sid = submit_to_form(topic, current_book["category"], knowledge)

        if success:
            submission_count += 1
            print(f"  Submitted: {sid}")

            if METADATA_AVAILABLE:
                try:
                    log_entry_metadata(
                        submission_id=sid,
                        source=source,
                        model=CLOUDFLARE_MODEL if source == "cloudflare" else "mistral-small-latest",
                        type="public_domain",
                        category=current_book["category"],
                        email=""
                    )
                    print(f"  [Metadata] Logged: {sid}")
                except Exception as e:
                    print(f"  [Metadata] Failed to log: {e}")
        else:
            failed_count += 1
            print(f"  Submission failed")

        state["current_index"] = i + 1
        save_state(state)

        if i < current_index + max_in_run - 1:
            wait = SUBMISSION_DELAY + random.randint(1, 10)
            print(f"  Waiting {wait}s...")
            time.sleep(wait)

    if state["current_index"] >= len(chunks):
        completed_books.append(current_book["id"])
        state["completed_books"] = completed_books
        state["current_book"] = None
        state["chunks"] = []
        state["current_index"] = 0
        save_state(state)
        print(f"\nBOOK COMPLETE: {current_book['title']}")
    else:
        print(f"\nPAUSED at chunk {state['current_index'] + 1} of {len(chunks)}")

    print("=" * 60)
    print(f"This run: {submission_count} submitted | {failed_count} failed | {validation_rejected} rejected")
    print(f"Total for this book: {state['current_index']} of {len(chunks)} processed")
    print("=" * 60)


if __name__ == "__main__":
    run_book_processor()
