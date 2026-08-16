"""
Book Processor — v2.1
======================
Automatically downloads public domain books from Project Gutenberg,
extracts text, splits into chunks, rewrites via Groq AI in
conversational African voice, and submits to the training form.

All books are pre-1927 — indisputably public domain.
Zero copyright risk. Fully automated.

Schedule: Runs daily. Processes one book per run.
Resumes from where it left off if interrupted.
- Banned organization filtering (FAO, WHO, UN, World Bank, IMF, etc.)
- Updated to llama-3.3-70b-versatile
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


# ===========================================================================
# Configuration
# ===========================================================================

TRAINING_FORM_URL = os.getenv("TRAINING_FORM_URL", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
SUBMISSION_DELAY = int(os.getenv("SUBMISSION_DELAY", "60"))
REQUEST_TIMEOUT = 90

GH_TOKEN = os.getenv("GH_TOKEN", "")
KNOWLEDGE_REPO = os.getenv("KNOWLEDGE_REPO", "")
GITHUB_API = "https://api.github.com"

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

STATE_FILE_PATH = "admin/book-processor-state.json"
MAX_CHUNKS_PER_RUN = 40
MIN_CHUNK_LENGTH = 300


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
# Book Download
# ===========================================================================

def download_book(book_id: str) -> Optional[str]:
    """Download a book from Project Gutenberg by ID. Returns full text or None."""
    urls = [
        GUTENBERG_URL_ALT.format(id=book_id),
        GUTENBERG_URL.format(id=book_id),
    ]
    for url in urls:
        try:
            print(f"  Downloading: {url}")
            sys.stdout.flush()
            response = requests.get(url, timeout=60, headers={"User-Agent": "BookProcessor/2.1"})
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
    """Remove Project Gutenberg header and footer boilerplate."""
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
    """Split book text into manageable chunks for AI rewriting."""
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
# AI Rewriting
# ===========================================================================

def rewrite_with_groq(chunk: str, book_title: str, book_author: str) -> str:
    """Rewrite a book chunk in conversational African voice using Groq."""
    if not GROQ_API_KEY:
        return ""

    system_prompt = (
        "You are a wise African storyteller sharing knowledge from classic literature. "
        "Rewrite the provided text in a warm, conversational voice that feels like "
        "an elder sharing wisdom around a fire. Keep all facts, names, dates, and "
        "key details accurate. Add practical lessons and African context where relevant. "
        "Write in first person. Write at least 400 words. "
        "Do NOT use markdown formatting. Write in plain text only. "
        + BANNED_INSTRUCTION
    )

    user_prompt = (
        f"This passage is from the public domain book '{book_title}' by {book_author}.\n\n"
        f"{chunk}\n\n"
        f"Rewrite this in a warm African storytelling voice. Keep the facts accurate. "
        f"Make it feel like wisdom being shared, not a book being read. "
        f"Write at least 400 words. Use plain text only."
    )

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.75,
        "max_tokens": 1500,
    }

    try:
        response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            if not _check_banned_content(content):
                return ""
            return content
        return ""
    except Exception as e:
        print(f"    Groq error: {e}")
        return ""


def rewrite_with_mistral(chunk: str, book_title: str, book_author: str) -> str:
    """Rewrite using Mistral (fallback)."""
    if not MISTRAL_API_KEY:
        return ""

    system_prompt = (
        "You are a wise African storyteller. Rewrite this passage in a warm, "
        "conversational voice. Keep facts accurate. Add African context. "
        "Write at least 400 words. Plain text only. "
        + BANNED_INSTRUCTION
    )
    user_prompt = (
        f"From '{book_title}' by {book_author}:\n\n{chunk}\n\n"
        f"Rewrite in African storytelling voice. 400+ words. Plain text."
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


def rewrite_chunk(chunk: str, book_title: str, book_author: str) -> str:
    """Rewrite a chunk using available AI APIs."""
    if GROQ_API_KEY:
        content = rewrite_with_groq(chunk, book_title, book_author)
        if content and len(content) >= MIN_CHUNK_LENGTH:
            return content

    if MISTRAL_API_KEY:
        content = rewrite_with_mistral(chunk, book_title, book_author)
        if content and len(content) >= MIN_CHUNK_LENGTH:
            return content

    return ""


# ===========================================================================
# Submission
# ===========================================================================

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


# ===========================================================================
# State File (Private Knowledge Repo)
# ===========================================================================

def _github_headers():
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
    """Download and process one public domain book per run."""
    print("=" * 60)
    print("Book Processor v2.1 — Project Gutenberg")
    print("=" * 60)
    print(f"Max chunks per run: {MAX_CHUNKS_PER_RUN}")
    print(f"Groq: {'ACTIVE' if GROQ_API_KEY else 'NOT SET'}")
    print(f"Mistral: {'ACTIVE' if MISTRAL_API_KEY else 'NOT SET'}")
    print(f"Banned orgs: {len(BANNED_ORGS)} organizations blocked")
    sys.stdout.flush()

    if not GROQ_API_KEY and not MISTRAL_API_KEY:
        print("ERROR: No AI API keys configured.")
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

    print(f"\nProcessing {max_in_run} chunks (of {len(chunks)} total)...")
    print("-" * 60)
    sys.stdout.flush()

    for i in range(current_index, current_index + max_in_run):
        if i >= len(chunks):
            break

        chunk = chunks[i]
        print(f"\n[{i + 1}/{len(chunks)}] Chunk {i + 1} ({len(chunk.split())} words)")

        knowledge = rewrite_chunk(chunk, current_book["title"], current_book["author"])
        if not knowledge:
            failed_count += 1
            print(f"  Failed to rewrite")
            state["current_index"] = i + 1
            save_state(state)
            continue

        if not _check_banned_content(knowledge):
            failed_count += 1
            print(f"  Failed: Content contains banned organizations")
            state["current_index"] = i + 1
            save_state(state)
            continue

        knowledge = re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'\1', knowledge)
        knowledge = re.sub(r'^#{1,6}\s+', '', knowledge, flags=re.MULTILINE)
        knowledge = knowledge.strip()

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
            print(f"  ✅ {sid}")
        else:
            failed_count += 1
            print(f"  ❌ Failed")

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
        print(f"\n📚 BOOK COMPLETE: {current_book['title']}")
    else:
        print(f"\n⏸️ PAUSED at chunk {state['current_index'] + 1} of {len(chunks)}")

    print("=" * 60)
    print(f"This run: {submission_count} submitted | {failed_count} failed")
    print(f"Total for this book: {state['current_index']} of {len(chunks)} processed")
    print("=" * 60)


if __name__ == "__main__":
    run_book_processor()
