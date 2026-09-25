"""
Human Voice Checker — v1.0
===========================
Validates that AI-generated content reads like human writing, not AI.
Checks for:
- Markdown symbols
- Banned AI words and phrases
- Sentence length (max 20 words)
- Complex vocabulary without explanation

Usage:
    from human_voice_checker import check_human_voice

    passed, reason = check_human_voice(content)
    if not passed:
        print(f"Content rejected: {reason}")

This module has NO external dependencies — only Python standard library.
"""

import re
from typing import Tuple, List, Dict, Any


# ===========================================================================
# Configuration
# ===========================================================================

# Maximum words per sentence
MAX_SENTENCE_WORDS = 20

# Minimum words per content (to catch empty responses)
MIN_CONTENT_WORDS = 300


# ===========================================================================
# Banned Words — Never Use
# ===========================================================================

BANNED_WORDS = [
    # Classic AI words
    "delve", "delves", "delved", "delving",
    "leverage", "leverages", "leveraged", "leveraging",
    "utilize", "utilizes", "utilized", "utilizing",
    "facilitate", "facilitates", "facilitated", "facilitating",
    "optimize", "optimizes", "optimized", "optimizing",
    "streamline", "streamlines", "streamlined", "streamlining",
    "robust",
    "comprehensive",
    "multifaceted",
    "nuanced",

    # Transitional AI words
    "furthermore",
    "moreover",
    "additionally",
    "consequently",
    "subsequently",
    "thus",
    "hence",
    "thereby",
    "nonetheless",
    "notwithstanding",

    # Other AI-favourite words
    "paradigm", "paradigms",
    "synergy", "synergies",
    "holistic",
    "pivotal",
    "myriad",
    "plethora",
    "catalyze", "catalyzes", "catalyzed",
    "exacerbate", "exacerbates", "exacerbated",
    "ameliorate", "ameliorates", "ameliorated",
    "ubiquitous",
    "quintessential",
    "juxtapose", "juxtaposes", "juxtaposed",
    "underscore", "underscores", "underscored",
    "delineate", "delineates", "delineated",
    "elucidate", "elucidates", "elucidated",
]


# Banned Phrases — Never Use
BANNED_PHRASES = [
    # AI opening lines
    "here is", "here's", "below is", "the following is",
    "certainly!", "of course!", "sure!", "great question",
    "absolutely!",

    # AI transition phrases
    "it is important to note",
    "it is worth mentioning",
    "it's important to note",
    "it's worth mentioning",
    "in conclusion",
    "in summary",
    "to sum up",
    "to summarize",
    "as previously mentioned",
    "as we have seen",
    "let us explore",
    "let's dive in",
    "let's explore",
    "without further ado",

    # AI header words
    "introduction:",
    "conclusion:",
    "summary:",
    "overview:",
    "steps:",
    "key points:",
    "takeaways:",
    "final thoughts:",
    "in this article",
    "in this piece",
    "in this discussion",

    # AI self-references
    "as an ai",
    "as a language model",
    "i am an ai",
    "based on my training",
    "i cannot",
    "i don't have personal",
]


# Markdown Symbols — Never Allow
MARKDOWN_SYMBOLS = [
    "**", "***",  # Bold / italic
    "##", "###",  # Headers
    "```",        # Code block
    "~~",         # Strikethrough
    "__",         # Underline
]


# Complex Words That Require Immediate Explanation
COMPLEX_WORDS_REQUIRING_EXPLANATION = [
    "agriculture",
    "infrastructure",
    "sustainable",
    "biodiversity",
    "ecosystem",
    "economic",
    "demographic",
    "bureaucracy",
    "hegemony",
    "sovereignty",
    "urbanization",
    "industrialization",
    "deforestation",
    "desertification",
    "sedimentation",
    "photosynthesis",
    "biodiversity",
    "epidemiology",
    "pharmacology",
    "anthropology",
]


# ===========================================================================
# Individual Checks
# ===========================================================================

def check_markdown_symbols(text: str) -> Tuple[bool, List[str]]:
    """
    Check for markdown symbols.
    Returns (clean, found_symbols).
    """
    found = []

    # Multi-char symbols first
    for symbol in MARKDOWN_SYMBOLS:
        if symbol in text:
            found.append(symbol)

    # Single-char markdown in specific positions
    # Line-starting list markers
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- "):
            if "-" not in found:
                found.append("- at line start")
        if stripped.startswith("* "):
            if "*" not in found:
                found.append("* at line start")
        if re.match(r'^\d+\.\s', stripped):
            if "1. at line start" not in found:
                found.append("1. at line start")
        if stripped.startswith("|"):
            if "|" not in found:
                found.append("|")

    # Single asterisks used as markdown
    # (asterisks surrounded by word chars)
    if re.search(r'\w\*\w', text):
        if "*" not in found:
            found.append("*")

    return len(found) == 0, found


def check_banned_words(text: str) -> Tuple[bool, List[str]]:
    """
    Check for banned AI words.
    Returns (clean, found_words).
    """
    text_lower = text.lower()
    found = []

    for word in BANNED_WORDS:
        # Use word boundaries to avoid matching inside other words
        pattern = rf'\b{re.escape(word)}\b'
        if re.search(pattern, text_lower):
            found.append(word)

    return len(found) == 0, found


def check_banned_phrases(text: str) -> Tuple[bool, List[str]]:
    """
    Check for banned AI phrases.
    Returns (clean, found_phrases).
    """
    text_lower = text.lower()
    found = []

    for phrase in BANNED_PHRASES:
        if phrase in text_lower:
            found.append(phrase)

    return len(found) == 0, found


def split_into_sentences(text: str) -> List[str]:
    """
    Split text into sentences.
    Handles common abbreviations to avoid false splits.
    """
    # Protect common abbreviations
    protected = text
    abbreviations = [
        "Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "St.", "Jr.", "Sr.",
        "etc.", "vs.", "i.e.", "e.g.", "a.m.", "p.m.",
    ]
    for abbr in abbreviations:
        protected = protected.replace(abbr, abbr.replace(".", "§§"))

    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', protected)

    # Restore abbreviations
    sentences = [s.replace("§§", ".") for s in sentences]

    # Filter empty
    return [s.strip() for s in sentences if s.strip()]


def check_sentence_length(text: str, max_words: int = MAX_SENTENCE_WORDS) -> Tuple[bool, List[str]]:
    """
    Check that no sentence exceeds max_words.
    Returns (clean, long_sentences).
    """
    sentences = split_into_sentences(text)
    long_sentences = []

    for sentence in sentences:
        words = sentence.split()
        if len(words) > max_words:
            preview = " ".join(words[:15]) + "..."
            long_sentences.append(f"{len(words)} words: {preview}")

    return len(long_sentences) == 0, long_sentences


def check_complex_words_explained(text: str) -> Tuple[bool, List[str]]:
    """
    Check that complex words are followed by an explanation.
    An explanation is a "—" or ":" or "(" within the next 10 words.
    Returns (clean, unexplained_words).
    """
    text_lower = text.lower()
    unexplained = []

    for word in COMPLEX_WORDS_REQUIRING_EXPLANATION:
        pattern = rf'\b{re.escape(word)}\b'
        for match in re.finditer(pattern, text_lower):
            # Look at the next 100 characters for explanation signals
            after = text_lower[match.end():match.end() + 100]
            has_explanation = (
                "—" in after or
                " - " in after or
                ":" in after or
                "(" in after or
                " that is " in after or
                " that means " in after or
                " which means " in after or
                " which is " in after
            )
            if not has_explanation:
                if word not in unexplained:
                    unexplained.append(word)
                break

    return len(unexplained) == 0, unexplained


def check_content_length(text: str) -> Tuple[bool, int]:
    """
    Check content meets minimum word count.
    Returns (valid, word_count).
    """
    word_count = len(text.split())
    return word_count >= MIN_CONTENT_WORDS, word_count


# ===========================================================================
# Main Checker
# ===========================================================================

def check_human_voice(text: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Run all checks and return combined result.

    Returns:
        (passed, details)
        passed: True if all checks pass
        details: dict with reasons for failure

    Example:
        passed, details = check_human_voice(content)
        if not passed:
            print(details['reasons'])
    """
    if not text or not text.strip():
        return False, {
            "passed": False,
            "reasons": ["empty_content"],
            "details": {},
        }

    all_reasons = []
    details = {}

    # Check markdown symbols
    clean, found = check_markdown_symbols(text)
    if not clean:
        all_reasons.append("markdown_symbols")
        details["markdown_symbols"] = found

    # Check banned words
    clean, found = check_banned_words(text)
    if not clean:
        all_reasons.append("banned_words")
        details["banned_words"] = found

    # Check banned phrases
    clean, found = check_banned_phrases(text)
    if not clean:
        all_reasons.append("banned_phrases")
        details["banned_phrases"] = found

    # Check sentence length
    clean, found = check_sentence_length(text)
    if not clean:
        all_reasons.append("long_sentences")
        details["long_sentences"] = found

    # Check complex words explained
    clean, found = check_complex_words_explained(text)
    if not clean:
        all_reasons.append("unexplained_complex_words")
        details["unexplained_complex_words"] = found

    # Check content length
    valid, word_count = check_content_length(text)
    details["word_count"] = word_count
    if not valid:
        all_reasons.append("too_short")
        details["min_words"] = MIN_CONTENT_WORDS

    passed = len(all_reasons) == 0

    return passed, {
        "passed": passed,
        "reasons": all_reasons,
        "details": details,
    }


# ===========================================================================
# Stripping Function (Companion to Checker)
# ===========================================================================

def strip_markdown_symbols(text: str) -> str:
    """
    Aggressively strip all markdown symbols.
    Use this after generation, then run check_human_voice to verify.
    """
    if not text:
        return ""

    # Remove bold/italic markers
    text = re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+?)_{1,3}', r'\1', text)

    # Remove headers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Remove list markers at line start
    text = re.sub(r'^\s*[\-\*\+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)

    # Remove code blocks
    text = re.sub(r'```[^`]*```', '', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # Remove strikethrough
    text = re.sub(r'~~([^~]+?)~~', r'\1', text)

    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Remove markdown tables
    text = re.sub(r'\|', '', text)

    # Remove horizontal rules
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)

    # Clean up excess whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)

    return text.strip()


def split_long_sentences(text: str, max_words: int = MAX_SENTENCE_WORDS) -> str:
    """
    Split sentences longer than max_words at natural break points.
    Tries commas, "and", "but", "so", "because".
    """
    if not text:
        return ""

    sentences = split_into_sentences(text)
    result = []

    for sentence in sentences:
        words = sentence.split()
        if len(words) <= max_words:
            result.append(sentence)
            continue

        # Try to split at natural break points
        # Look for commas, "and", "but", "so", "because"
        parts = re.split(r'(,\s+|\s+(?:and|but|so|because|while|although|however)\s+)', sentence)

        current = ""
        current_words = 0

        for part in parts:
            part = part.strip()
            if not part:
                continue

            part_words = len(part.split())

            # If this is a connector, attach to current
            if part.lower() in ["and", "but", "so", "because", "while", "although", "however"]:
                current += " " + part
                continue

            if part.startswith(","):
                current += part
                continue

            if current_words + part_words <= max_words:
                if current:
                    current += " " + part
                else:
                    current = part
                current_words = len(current.split())
            else:
                if current:
                    result.append(current.strip())
                current = part
                current_words = part_words

        if current:
            result.append(current.strip())

    # If still too long, just return the original sentence
    # (regex splitting may not always work)
    final = []
    for sent in result:
        if len(sent.split()) <= max_words:
            final.append(sent)
        else:
            final.append(sent)  # Keep as-is if we can't split

    return " ".join(final)


# ===========================================================================
# Self-Test
# ===========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Human Voice Checker — Self-Test")
    print("=" * 60)

    # Test 1: Good content
    good = "The farmer wakes early. He tends the land with care. Water is precious in dry months. He gathers rain in clay pots. His crops survive this way."
    passed, details = check_human_voice(good)
    print(f"\nTest 1 (good content): {'✅ PASS' if passed else '❌ FAIL'}")
    print(f"  Details: {details['reasons']}")

    # Test 2: With markdown
    bad_md = "**Adowa Dance** is a dance. - It is performed in Ghana. ## Steps: - Stand upright. - Move your hips."
    passed, details = check_human_voice(bad_md)
    print(f"\nTest 2 (markdown): {'✅ PASS' if passed else '❌ FAIL'}")
    print(f"  Reasons: {details['reasons']}")
    print(f"  Symbols: {details['details'].get('markdown_symbols', [])}")

    # Test 3: Banned words
    bad_words = "We will delve into this. Furthermore, we leverage technology to optimize results. In conclusion, this is comprehensive."
    passed, details = check_human_voice(bad_words)
    print(f"\nTest 3 (banned words): {'✅ PASS' if passed else '❌ FAIL'}")
    print(f"  Reasons: {details['reasons']}")
    print(f"  Words: {details['details'].get('banned_words', [])}")
    print(f"  Phrases: {details['details'].get('banned_phrases', [])}")

    # Test 4: Long sentences
    long_sent = "The farmer who lives in the northern part of the country and who has been farming for many years knows that the rainy season is the best time to plant his crops because the soil holds water well during this period of the year."
    passed, details = check_human_voice(long_sent)
    print(f"\nTest 4 (long sentence): {'✅ PASS' if passed else '❌ FAIL'}")
    print(f"  Reasons: {details['reasons']}")
    print(f"  Long: {details['details'].get('long_sentences', [])}")

    print("\n" + "=" * 60)
    print("Self-test complete.")
    print("=" * 60)
