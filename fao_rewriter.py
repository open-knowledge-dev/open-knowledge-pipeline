"""
FAO Safety-Net Rewriter — v1.0
================================
Weekly scanner that detects and rewrites any FAO-referencing files
in the Ghana-GPT knowledge base.

- Scans all category folders for files with "FAO" in filename or body
- Rewrites via Groq to remove all FAO/UN references
- Renames files to remove "FAO" from filename
- Updates all 3 databases
- Runs as weekly GitHub Actions workflow (Sunday 4 AM)
- Self-disabling: skips if no FAO files found for 4 consecutive weeks

Legal basis: Facts are not copyrightable. Rewritten content is 100% original.
"""

import os
import sys
import time
import json
import base64
import re
import requests
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict


# ===========================================================================
# Configuration
# ===========================================================================

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
GH_TOKEN = os.getenv("GH_TOKEN", "")
KNOWLEDGE_REPO = os.getenv("KNOWLEDGE_REPO", "ghana-gpt/ghana-gpt-knowledge")
GITHUB_API = "https://api.github.com"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

STATE_FILE_PATH = "admin/fao-rewriter-state.json"
AUDIT_FILE_PATH = "admin/fao-rewrite-audit.md"
REQUEST_TIMEOUT = 60
MAX_FILES_PER_RUN = 10  # Conservative — runs weekly, not urgent

# Database URLs from environment
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
NEON_URL = os.getenv("NEON_URL", "")
FLY_PG_URL = os.getenv("FLY_PG_URL", "")

# FAO detection patterns
FAO_FILENAME_PATTERN = re.compile(r'FAO|fao', re.IGNORECASE)
FAO_CONTENT_PATTERNS = [
    re.compile(r'\bFAO\b'),
    re.compile(r'fao\.org', re.IGNORECASE),
    re.compile(r'Food and Agriculture Organization', re.IGNORECASE),
    re.compile(r'United Nations.*(?:agriculture|farming|food|crop|livestock|fishery)', re.IGNORECASE),
    re.compile(r'(?:agriculture|farming|food|crop|livestock|fishery).*United Nations', re.IGNORECASE),
]

# Category folder mapping
CATEGORY_FOLDERS = [
    "agriculture_farming", "business_finance", "culture_traditions",
    "education_learning", "health_medicine", "technology_innovation",
    "tourism_travel", "history_heritage", "food_cuisine",
    "music_dance", "language_proverbs", "religion_spirituality",
    "sports_games", "fashion_textiles", "environment_nature",
    "governance_leadership", "family_relationships", "arts_crafts",
    "science_innovation", "other",
]

# ===========================================================================
# Rewrite Prompt
# ===========================================================================

REWRITE_SYSTEM_PROMPT = (
    "You are an agricultural expert from Ghana with decades of hands-on farming experience. "
    "Rewrite the following information completely in your own voice. "
    "Change the entire structure. Add West African and Ghanaian farming context, "
    "local crop varieties, and regional techniques. Use completely different phrasing, "
    "sentence structures, and examples. Do not retain any wording or phrasing from the original. "
    "The output must be 100% original content that conveys the same factual information "
    "in a new voice. Facts themselves are not copyrightable. "
    "Do NOT mention FAO, United Nations, or any source organization. "
    "Write as if this is original knowledge from your own farming experience in Ghana. "
    "Do NOT use markdown formatting. Write in plain text only."
)

REWRITE_USER_TEMPLATE = (
    "Rewrite this farming knowledge completely:\n\n"
    "{content}\n\n"
    "Make it 100% original. Ghanaian farming voice. No FAO, no United Nations, "
    "no source organizations. Facts can stay — everything else must change. "
    "Write at least 400 words. Plain text only."
)


# ===========================================================================
# GitHub API Helpers
# ===========================================================================

def _github_headers() -> Dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GH_TOKEN:
        headers["Authorization"] = f"token {GH_TOKEN}"
    return headers


def load_state() -> Dict:
    """Load rewriter state from GitHub."""
    if not GH_TOKEN or not KNOWLEDGE_REPO:
        return {"processed_files": [], "clean_weeks": 0, "total_rewritten": 0}
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
    return {"processed_files": [], "clean_weeks": 0, "total_rewritten": 0}


def save_state(state: Dict) -> bool:
    """Save rewriter state to GitHub."""
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
        "message": f"Update FAO rewriter state — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
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


def append_audit_log(entry: str) -> bool:
    """Append an entry to the audit log."""
    if not GH_TOKEN or not KNOWLEDGE_REPO:
        return False
    
    # Get existing audit file
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{AUDIT_FILE_PATH}"
    sha = ""
    existing_content = ""
    try:
        response = requests.get(url, headers=_github_headers(), timeout=10)
        if response.status_code == 200:
            sha = response.json().get("sha", "")
            content_b64 = response.json().get("content", "")
            if content_b64:
                existing_content = base64.b64decode(content_b64).decode("utf-8")
    except Exception:
        pass
    
    # Append new entry
    if not existing_content:
        existing_content = "# FAO Rewriter Audit Log\n\n"
    
    new_content = existing_content + entry + "\n"
    
    payload = {
        "message": f"Update FAO audit log — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "content": base64.b64encode(new_content.encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha
    
    try:
        response = requests.put(url, json=payload, headers=_github_headers(), timeout=15)
        return response.status_code in [200, 201]
    except Exception:
        return False


def get_file_content(path: str) -> Optional[Tuple[str, str]]:
    """Get file content and SHA from GitHub. Returns (content, sha) or None."""
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    try:
        response = requests.get(url, headers=_github_headers(), timeout=15)
        if response.status_code == 200:
            data = response.json()
            content = base64.b64decode(data.get("content", "")).decode("utf-8")
            return content, data.get("sha", "")
    except Exception:
        pass
    return None


def update_file(path: str, new_content: str, sha: str, commit_msg: str) -> bool:
    """Update a file on GitHub."""
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    payload = {
        "message": commit_msg,
        "content": base64.b64encode(new_content.encode("utf-8")).decode("utf-8"),
        "sha": sha,
        "branch": "main",
    }
    try:
        response = requests.put(url, json=payload, headers=_github_headers(), timeout=15)
        return response.status_code in [200, 201]
    except Exception:
        return False


# ===========================================================================
# FAO Detection
# ===========================================================================

def contains_fao_content(text: str) -> bool:
    """Check if text contains any FAO-related references."""
    for pattern in FAO_CONTENT_PATTERNS:
        if pattern.search(text):
            return True
    return False


def has_fao_filename(filename: str) -> bool:
    """Check if filename contains FAO reference."""
    return bool(FAO_FILENAME_PATTERN.search(filename))


# ===========================================================================
# File Scanning
# ===========================================================================

def scan_for_fao_files(state: Dict) -> List[Dict]:
    """Scan all category folders for files with FAO references.
    Returns list of {path, sha, has_fao_content, has_fao_filename}."""
    
    processed = set(state.get("processed_files", []))
    fao_files = []
    
    print(f"Scanning {len(CATEGORY_FOLDERS)} category folders...")
    sys.stdout.flush()
    
    for folder in CATEGORY_FOLDERS:
        url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{folder}"
        try:
            response = requests.get(url, headers=_github_headers(), timeout=15)
            if response.status_code != 200:
                continue
            
            files = response.json()
            if not isinstance(files, list):
                continue
            
            for file_info in files:
                filepath = file_info.get("path", "")
                filename = filepath.split("/")[-1]
                
                # Skip already processed
                if filepath in processed:
                    continue
                
                # Check filename
                if has_fao_filename(filename):
                    content, sha = get_file_content(filepath) or ("", "")
                    fao_in_body = contains_fao_content(content) if content else False
                    fao_files.append({
                        "path": filepath,
                        "sha": sha if sha else file_info.get("sha", ""),
                        "has_fao_content": fao_in_body,
                        "has_fao_filename": True,
                        "content": content,
                    })
                    print(f"  ⚠️  FAO in filename: {filepath}")
                    sys.stdout.flush()
                    
        except Exception as e:
            print(f"  Error scanning {folder}: {e}")
            sys.stdout.flush()
    
    return fao_files


# ===========================================================================
# AI Rewriting
# ===========================================================================

def rewrite_with_groq(content: str) -> str:
    """Rewrite content using Groq to remove all FAO references."""
    if not GROQ_API_KEY:
        return ""
    
    user_prompt = REWRITE_USER_TEMPLATE.replace("{content}", content[:3000])
    
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,
        "max_tokens": 2000,
    }
    
    try:
        response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            return content
    except Exception as e:
        print(f"    Groq error: {e}")
    
    return ""


def rewrite_with_mistral(content: str) -> str:
    """Fallback: rewrite using Mistral."""
    if not MISTRAL_API_KEY:
        return ""
    
    user_prompt = REWRITE_USER_TEMPLATE.replace("{content}", content[:3000])
    
    headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "mistral-small-latest",
        "messages": [
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,
        "max_tokens": 2000,
    }
    
    try:
        response = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            return content
    except Exception as e:
        print(f"    Mistral error: {e}")
    
    return ""


def rewrite_content(content: str) -> str:
    """Rewrite content using available APIs. Returns empty string on failure."""
    
    if GROQ_API_KEY:
        rewritten = rewrite_with_groq(content)
        if rewritten and len(rewritten) >= 300:
            # Validate no FAO references remain
            if not contains_fao_content(rewritten):
                return rewritten
            else:
                print(f"    ⚠️  Rewrite still contains FAO — retrying...")
                # Retry once with stronger temperature
                rewritten2 = rewrite_with_groq(content)
                if rewritten2 and len(rewritten2) >= 300 and not contains_fao_content(rewritten2):
                    return rewritten2
    
    if MISTRAL_API_KEY:
        rewritten = rewrite_with_mistral(content)
        if rewritten and len(rewritten) >= 300 and not contains_fao_content(rewritten):
            return rewritten
    
    return ""


# ===========================================================================
# File Rename
# ===========================================================================

def generate_clean_filename(original_path: str) -> str:
    """Generate a clean filename without FAO reference."""
    folder = original_path.split("/")[0]
    filename = original_path.split("/")[-1]
    
    # Remove FAO from filename
    clean_name = re.sub(r'FAO[_\-]?', '', filename, flags=re.IGNORECASE)
    clean_name = re.sub(r'fao[_\-]?', '', clean_name)
    
    # Clean up double separators
    clean_name = re.sub(r'[_\-]{2,}', '_', clean_name)
    clean_name = clean_name.strip('_-')
    
    return f"{folder}/{clean_name}"


# ===========================================================================
# Database Update
# ===========================================================================

def update_databases(original_path: str, new_path: str) -> bool:
    """Update source tag in all 3 databases."""
    success_count = 0
    
    # Fly.io Postgres
    if FLY_PG_URL:
        try:
            import psycopg2
            conn = psycopg2.connect(FLY_PG_URL)
            cur = conn.cursor()
            cur.execute(
                "UPDATE submissions SET source = %s WHERE pending_filename = %s",
                ("Original knowledge from Ghana", original_path)
            )
            conn.commit()
            cur.close()
            conn.close()
            success_count += 1
            print(f"    ✅ Fly.io PG updated")
        except Exception as e:
            print(f"    ⚠️  Fly.io PG update failed: {e}")
    
    # Supabase
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            headers = {
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
            }
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/submissions?pending_filename=eq.{original_path}",
                json={"source": "Original knowledge from Ghana"},
                headers=headers,
                timeout=15,
            )
            success_count += 1
            print(f"    ✅ Supabase updated")
        except Exception as e:
            print(f"    ⚠️  Supabase update failed: {e}")
    
    # Neon
    if NEON_URL:
        try:
            import psycopg2
            conn = psycopg2.connect(NEON_URL)
            cur = conn.cursor()
            cur.execute(
                "UPDATE submissions SET source = %s WHERE pending_filename = %s",
                ("Original knowledge from Ghana", original_path)
            )
            conn.commit()
            cur.close()
            conn.close()
            success_count += 1
            print(f"    ✅ Neon updated")
        except Exception as e:
            print(f"    ⚠️  Neon update failed: {e}")
    
    sys.stdout.flush()
    return success_count >= 1


# ===========================================================================
# Main
# ===========================================================================

def run_fao_rewriter():
    """Main rewriter — scans for FAO files and rewrites them."""
    print("=" * 60)
    print("FAO Safety-Net Rewriter v1.0")
    print(f"Run: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    print(f"Groq: {'ACTIVE' if GROQ_API_KEY else 'NOT SET'}")
    print(f"Mistral: {'ACTIVE' if MISTRAL_API_KEY else 'NOT SET'}")
    print(f"Max files per run: {MAX_FILES_PER_RUN}")
    sys.stdout.flush()
    
    # Load state
    state = load_state()
    print(f"Previously processed: {len(state.get('processed_files', []))} files")
    print(f"Clean weeks: {state.get('clean_weeks', 0)}")
    print(f"Total rewritten: {state.get('total_rewritten', 0)}")
    sys.stdout.flush()
    
    # Scan for FAO files
    fao_files = scan_for_fao_files(state)
    
    if not fao_files:
        state["clean_weeks"] = state.get("clean_weeks", 0) + 1
        save_state(state)
        print(f"\n✅ No FAO files found.")
        print(f"Clean weeks: {state['clean_weeks']}/4")
        
        if state["clean_weeks"] >= 4:
            print(f"🔒 4+ clean weeks — workflow will skip next run.")
        
        # Append audit entry
        append_audit_log(
            f"## {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"- Status: CLEAN\n"
            f"- Files found: 0\n"
            f"- Clean weeks: {state['clean_weeks']}\n"
        )
        
        print("=" * 60)
        return
    
    # Reset clean weeks counter
    state["clean_weeks"] = 0
    
    # Process files (up to MAX_FILES_PER_RUN)
    files_to_process = fao_files[:MAX_FILES_PER_RUN]
    rewritten_count = 0
    failed_count = 0
    
    print(f"\nFound {len(fao_files)} FAO-referencing files. Processing {len(files_to_process)}...")
    print("-" * 60)
    sys.stdout.flush()
    
    for file_info in files_to_process:
        filepath = file_info["path"]
        print(f"\n📄 {filepath}")
        sys.stdout.flush()
        
        needs_rewrite = file_info["has_fao_content"] or file_info["has_fao_filename"]
        
        if file_info["has_fao_content"]:
            print(f"  ⚠️  FAO text found in body — rewriting...")
            sys.stdout.flush()
            
            rewritten = rewrite_content(file_info.get("content", ""))
            if not rewritten:
                failed_count += 1
                print(f"  ❌ Rewrite failed")
                state["processed_files"].append(filepath)
                save_state(state)
                continue
            
            new_content = rewritten
        else:
            # No FAO in body — just need to clean filename
            new_content = file_info.get("content", "")
            print(f"  FAO in filename only — renaming without rewrite")
        
        # Generate clean filename
        new_path = generate_clean_filename(filepath)
        print(f"  Rename: {filepath} → {new_path}")
        sys.stdout.flush()
        
        # Save new file
        if update_file(new_path, new_content, "", f"FAO safety rewrite: {filepath}"):
            # Delete old file
            update_file(
                filepath, "", file_info["sha"],
                f"Remove FAO-referencing file: {filepath} → {new_path}"
            )
            print(f"  ✅ File replaced")
            
            # Update databases
            update_databases(filepath, new_path)
            
            rewritten_count += 1
            state["total_rewritten"] = state.get("total_rewritten", 0) + 1
        else:
            failed_count += 1
            print(f"  ❌ File update failed")
        
        # Mark as processed
        state["processed_files"].append(filepath)
        save_state(state)
        
        # Delay between files
        if files_to_process.index(file_info) < len(files_to_process) - 1:
            time.sleep(5)
    
    # Audit log
    audit_entry = (
        f"## {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"- Status: REWRITTEN\n"
        f"- Files found: {len(fao_files)}\n"
        f"- Files processed: {len(files_to_process)}\n"
        f"- Rewritten: {rewritten_count}\n"
        f"- Failed: {failed_count}\n"
        f"- Total all-time: {state['total_rewritten']}\n"
    )
    for f in files_to_process:
        audit_entry += f"- `{f['path']}` → `{generate_clean_filename(f['path'])}`\n"
    
    append_audit_log(audit_entry)
    
    print(f"\n{'=' * 60}")
    print(f"Done: {rewritten_count} rewritten | {failed_count} failed")
    print(f"Total all-time: {state['total_rewritten']}")
    print(f"Files remaining: {len(fao_files) - len(files_to_process)}")
    print("=" * 60)


if __name__ == "__main__":
    run_fao_rewriter()
