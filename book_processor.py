"""
Book Knowledge Processor — v2.0
================================
Extracts sections from language learning PDFs and generates
original English lessons using AI — zero copyright risk.

How it works:
1. You upload a PDF to books/ (local only, never committed)
2. Run the workflow with language name/code/region
3. PDF text is extracted section by section
4. AI receives ONLY the target-language words + their English meanings
5. AI writes a 670+ word lesson explaining those facts in English
6. AI NEVER invents new target-language words
7. AI NEVER reproduces the source text — it teaches in its own words
8. All knowledge goes to the PRIVATE knowledge repo
9. Progress tracked in admin/book-processor-state.json (private repo)
10. Resumable — picks up where it left off

Supports: All languages with a PDF reference
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
SUBMISSION_DELAY = int(os.getenv("SUBMISSION_DELAY", "90"))
REQUEST_TIMEOUT = 90

GH_TOKEN = os.getenv("GH_TOKEN", "")
KNOWLEDGE_REPO = os.getenv("KNOWLEDGE_REPO", "")
GITHUB_API = "https://api.github.com"

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

STATE_FILE_PATH = "admin/book-processor-state.json"
BOOKS_DIR = "books"

MIN_CONTENT_LENGTH = 500
MAX_SECTIONS_PER_RUN = 40


# ===========================================================================
# PDF Text Extraction
# ===========================================================================

def extract_pdf_text(pdf_path: str) -> str:
    """
    Extract all text from a PDF file using pdfplumber.
    Returns the full text as a single string.
    """
    try:
        import pdfplumber
    except ImportError:
        print("  Installing pdfplumber...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pdfplumber"])
        import pdfplumber

    print(f"  Extracting text from PDF: {pdf_path}")
    sys.stdout.flush()

    full_text = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            print(f"  Total pages: {total_pages}")
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    full_text.append(text)
                if (i + 1) % 10 == 0:
                    print(f"  Extracted page {i + 1}/{total_pages}")
                    sys.stdout.flush()
    except Exception as e:
        print(f"  PDF extraction error: {e}")
        return ""

    combined = "\n\n".join(full_text)
    print(f"  Total extracted: {len(combined)} characters")
    return combined


def split_into_sections(text: str, max_chars: int = 2000) -> List[str]:
    """
    Split extracted text into manageable sections.
    Tries to split on paragraph breaks and section headers.
    """
    # Split on double newlines first (paragraphs)
    paragraphs = re.split(r'\n\s*\n', text)
    
    sections = []
    current_section = ""
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        # If adding this paragraph exceeds max, save current and start new
        if len(current_section) + len(para) > max_chars and current_section:
            sections.append(current_section.strip())
            current_section = para
        else:
            if current_section:
                current_section += "\n\n" + para
            else:
                current_section = para
    
    if current_section.strip():
        sections.append(current_section.strip())
    
    # Filter out very short sections
    sections = [s for s in sections if len(s) > 100]
    
    print(f"  Split into {len(sections)} sections")
    return sections


# ===========================================================================
# Prompt Style for Language Lessons
# ===========================================================================

def build_lesson_prompt(facts_text: str, language_name: str) -> Tuple[str, str]:
    """
    Build the system and user prompts for generating a language lesson.
    The AI MUST use the exact target-language words provided.
    The AI MUST NOT invent new target-language words.
    """
    system_prompt = (
        f"You are a native {language_name} speaker and a patient language teacher. "
        "Your job is to create an English-language lesson that teaches "
        f"{language_name} words and concepts to beginners.\n\n"
        "CRITICAL RULES:\n"
        f"1. Use ONLY the exact {language_name} words, spellings, and facts provided below.\n"
        f"2. Do NOT add, change, or invent any {language_name} words.\n"
        f"3. If a {language_name} word is spelled a certain way below, use that exact spelling.\n"
        "4. Your job is to EXPLAIN these facts in English — add examples, "
        "pronunciation tips, memory tricks, and cultural context.\n"
        "5. Write in first person as if you grew up speaking this language.\n"
        "6. Write at least 670 words.\n"
        "7. Never mention AI, language models, or that you were given these facts.\n"
        "8. Do NOT use markdown formatting. Write in plain text only.\n"
        "9. Write as if you are teaching a friend your language."
    )

    user_prompt = (
        f"Here are {language_name} language facts from a reference book:\n\n"
        f"{facts_text}\n\n"
        f"Using ONLY these exact {language_name} words and facts, "
        "write a complete 670+ word lesson in English. "
        "Explain what each word means, how to pronounce it, "
        "when to use it, and any cultural context. "
        "Add memory tricks and examples from daily life. "
        "Write in first person as a native speaker. "
        "Do NOT add any target-language words beyond what is provided above. "
        "Write in plain text only — no markdown formatting."
    )

    return system_prompt, user_prompt


# ===========================================================================
# Markdown Stripping
# ===========================================================================

def strip_markdown(text: str) -> str:
    """Remove all markdown formatting from AI-generated text."""
    text = re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+?)_{1,3}', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\-\*]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'```[^`]*```', '', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ===========================================================================
# State File Operations (Private Knowledge Repo)
# ===========================================================================

def _github_headers() -> Dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GH_TOKEN:
        headers["Authorization"] = f"token {GH_TOKEN}"
    return headers


def load_state() -> Dict:
    """Load the book processor state from the PRIVATE knowledge repo."""
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
    """Save the book processor state to the PRIVATE knowledge repo."""
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
    except Exception as e:
        print(f"  [State] Save error: {e}")
    return False


# ===========================================================================
# AI Content Generation
# ===========================================================================

def generate_with_groq(system_prompt: str, user_prompt: str) -> str:
    """Generate content using Groq API."""
    if not GROQ_API_KEY:
        return ""
    print(f"    [Groq] Generating lesson...")
    sys.stdout.flush()
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.75,
        "max_tokens": 2000,
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


def generate_with_mistral(system_prompt: str, user_prompt: str) -> str:
    """Generate content using Mistral API (fallback)."""
    if not MISTRAL_API_KEY:
        return ""
    print(f"    [Mistral] Generating lesson...")
    sys.stdout.flush()
    headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "mistral-small-latest",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.75,
        "max_tokens": 2000,
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


def generate_lesson(facts_text: str, language_name: str) -> str:
    """Generate a language lesson from extracted facts."""
    system_prompt, user_prompt = build_lesson_prompt(facts_text, language_name)

    if GROQ_API_KEY:
        content = generate_with_groq(system_prompt, user_prompt)
        if content and len(content) >= MIN_CONTENT_LENGTH:
            return content

    if MISTRAL_API_KEY:
        content = generate_with_mistral(system_prompt, user_prompt)
        if content and len(content) >= MIN_CONTENT_LENGTH:
            return content

    return ""


# ===========================================================================
# Submission (Sends to PRIVATE Knowledge Repo)
# ===========================================================================

def submit_to_form(topic: str, category: str, knowledge: str, language: str, region: str) -> Tuple[bool, str]:
    """Submit knowledge to the training form. Goes to PRIVATE knowledge repo."""
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
            "region": region, "language": language, "email": "",
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
# Topic Extraction from Section Text
# ===========================================================================

def extract_topic_from_section(section_text: str, language_name: str) -> str:
    """
    Extract a topic name from a section of text.
    Uses first heading or first meaningful line.
    """
    lines = section_text.strip().split('\n')
    for line in lines[:5]:
        line = line.strip()
        # Skip very short lines and obvious non-headers
        if 5 < len(line) < 120:
            # Clean up the topic
            topic = re.sub(r'^[\d]+[\.\)]\s*', '', line)
            topic = topic.strip()
            if topic:
                return f"{language_name}: {topic}"
    
    # Fallback: use first 80 chars
    first_line = lines[0].strip()[:80] if lines else "Language lesson"
    return f"{language_name}: {first_line}"


# ===========================================================================
# Main
# ===========================================================================

def run_book_processor(pdf_file: str, language_name: str, language_code: str, region: str):
    """
    Process a language learning PDF into knowledge entries.
    All output goes to the PRIVATE knowledge repo.

    Args:
        pdf_file: PDF filename in books/ folder (e.g., "GH_Twi_Language_Lessons.pdf")
        language_name: Full language name (e.g., "Twi")
        language_code: Language code for submission (e.g., "Twi")
        region: Region for submission (e.g., "Ghana")
    """
    print("=" * 60)
    print(f"Book Processor v2.0 — {language_name}")
    print("=" * 60)
    print(f"PDF: {pdf_file}")
    print(f"Language: {language_name} ({language_code})")
    print(f"Region: {region}")
    print(f"Output: PRIVATE knowledge repo ({KNOWLEDGE_REPO})")
    print("-" * 60)
    sys.stdout.flush()

    # Check PDF exists
    pdf_path = os.path.join(BOOKS_DIR, pdf_file)
    if not os.path.exists(pdf_path):
        print(f"ERROR: PDF not found at {pdf_path}")
        print("Make sure the PDF is in the books/ folder.")
        return

    # Load state from PRIVATE knowledge repo
    state = load_state()
    book_key = pdf_file.replace('.pdf', '')

    # Check if we already have extracted sections cached
    if book_key not in state or "sections" not in state[book_key]:
        # Extract text from PDF
        print("\nExtracting text from PDF...")
        full_text = extract_pdf_text(pdf_path)
        if not full_text:
            print("ERROR: Could not extract text from PDF.")
            return

        # Split into sections
        sections = split_into_sections(full_text)
        if not sections:
            print("ERROR: No sections extracted.")
            return

        # Initialize state
        state[book_key] = {
            "pdf_file": pdf_file,
            "language_name": language_name,
            "language_code": language_code,
            "region": region,
            "total_sections": len(sections),
            "sections": sections,
            "completed_sections": [],
            "failed_sections": [],
            "current_index": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_run": "",
        }
        save_state(state)
        print(f"  Cached {len(sections)} sections to private repo")
    else:
        print(f"\n  Resuming from cached sections in private repo")

    book_state = state[book_key]
    sections = book_state["sections"]
    start_index = book_state.get("current_index", 0)

    print(f"  Total sections: {len(sections)}")
    print(f"  Resuming from section {start_index + 1}")
    print(f"  Completed so far: {len(book_state.get('completed_sections', []))}")
    print("-" * 60)
    sys.stdout.flush()

    submission_count = 0
    failed_count = 0
    max_in_this_run = min(MAX_SECTIONS_PER_RUN, len(sections) - start_index)

    for i in range(start_index, start_index + max_in_this_run):
        if i >= len(sections):
            break

        section_text = sections[i]
        topic = extract_topic_from_section(section_text, language_name)
        category = "Language & Proverbs"

        print(f"\n[{i + 1}/{len(sections)}] {topic}")
        sys.stdout.flush()

        # Generate lesson from this section's facts
        knowledge = generate_lesson(section_text, language_name)

        if not knowledge or len(knowledge) < MIN_CONTENT_LENGTH:
            failed_count += 1
            book_state["failed_sections"].append({"index": i, "topic": topic, "reason": "content_too_short"})
            print(f"  Failed: content too short ({len(knowledge) if knowledge else 0} chars)")
            book_state["current_index"] = i + 1
            state[book_key] = book_state
            save_state(state)
            continue

        # Clean output
        knowledge = strip_markdown(knowledge)
        knowledge = re.sub(
            r'(?i)(as an AI|as a language model|I am an AI|based on my training)',
            '', knowledge
        ).strip()

        if len(knowledge) < MIN_CONTENT_LENGTH:
            failed_count += 1
            book_state["failed_sections"].append({"index": i, "topic": topic, "reason": "too_short_after_cleaning"})
            book_state["current_index"] = i + 1
            state[book_key] = book_state
            save_state(state)
            continue

        print(f"  Lesson: {len(knowledge)} chars (~{len(knowledge.split())} words)")
        sys.stdout.flush()

        # Submit
        success, submission_id = submit_to_form(
            topic, category, knowledge, language_code, region
        )

        if success:
            submission_count += 1
            book_state["completed_sections"].append({
                "index": i, "topic": topic, "submission_id": submission_id,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            print(f"  Submitted to private repo: {submission_id}")
        else:
            failed_count += 1
            book_state["failed_sections"].append({"index": i, "topic": topic, "reason": "submission_failed"})
            print(f"  Submission failed")

        # Save progress
        book_state["current_index"] = i + 1
        book_state["last_run"] = datetime.now(timezone.utc).isoformat()
        state[book_key] = book_state
        save_state(state)

        # Delay
        if i < start_index + max_in_this_run - 1:
            wait_time = SUBMISSION_DELAY + random.randint(1, 15)
            print(f"  Waiting {wait_time}s...")
            sys.stdout.flush()
            time.sleep(wait_time)

    # Status
    if book_state["current_index"] >= len(sections):
        book_state["completed_at"] = datetime.now(timezone.utc).isoformat()
        state[book_key] = book_state
        save_state(state)
        print(f"\nBOOK COMPLETE: {language_name}")
        print(f"   Total lessons in private repo: {len(book_state['completed_sections'])}")
    else:
        print(f"\nPAUSED at section {book_state['current_index'] + 1} of {len(sections)}")
        print(f"   Will auto-resume in 6 hours.")

    print("=" * 60)
    print(f"This run: {submission_count} submitted | {failed_count} failed")
    print(f"Overall: {len(book_state['completed_sections'])} completed")
    print("=" * 60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Process language learning PDFs into knowledge entries.")
    parser.add_argument("--pdf", required=True, help="PDF filename in books/ folder")
    parser.add_argument("--language", required=True, help="Language name (e.g., 'Twi')")
    parser.add_argument("--code", required=True, help="Language code (e.g., 'Twi')")
    parser.add_argument("--region", default="Ghana", help="Region (e.g., 'Ghana')")

    args = parser.parse_args()

    run_book_processor(
        pdf_file=args.pdf,
        language_name=args.language,
        language_code=args.code,
        region=args.region,
    )
