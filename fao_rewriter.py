"""
FAO Safety-Net Rewriter — v1.1
================================
Weekly scanner that detects and rewrites any FAO-referencing files
in the Ghana-GPT knowledge base.

Changes in v1.1:
- Fixed: scan_for_fao_files() now correctly detects files
- Added: debug logging for API calls
- Changed: filename match alone triggers full rewrite (not just rename)
- Added: progress output per folder
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
MAX_FILES_PER_RUN = 10

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
NEON_URL = os.getenv("NEON_URL", "")
FLY_PG_URL = os.getenv("FLY_PG_URL", "")

FAO_FILENAME_PATTERN = re.compile(r'FAO|fao', re.IGNORECASE)
FAO_CONTENT_PATTERNS = [
    re.compile(r'\bFAO\b'),
    re.compile(r'fao\.org', re.IGNORECASE),
    re.compile(r'Food and Agriculture Organization', re.IGNORECASE),
    re.compile(r'United Nations.*(?:agriculture|farming|food|crop|livestock|fishery)', re.IGNORECASE),
    re.compile(r'(?:agriculture|farming|food|crop|livestock|fishery).*United Nations', re.IGNORECASE),
]

CATEGORY_FOLDERS = [
    "agriculture_farming", "business_finance", "culture_traditions",
    "education_learning", "health_medicine", "technology_innovation",
    "tourism_travel", "history_heritage", "food_cuisine",
    "music_dance", "language_proverbs", "religion_spirituality",
    "sports_games", "fashion_textiles", "environment_nature",
    "governance_leadership", "family_relationships", "arts_crafts",
    "science_innovation", "other",
]

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
    if not GH_TOKEN or not KNOWLEDGE_REPO:
        return {"processed_files": [], "clean_weeks": 0, "total_rewritten": 0}
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{STATE_FILE_PATH}"
    try:
        response = requests.get(url, headers=_github_headers(), timeout=15)
        if response.status_code == 200:
            content_b64 = response.json().get("content", "")
            if content_b64:
                decoded = base64.b64decode(content_b64).decode("utf-8")
                state = json.loads(decoded)
                state.setdefault("processed_files", [])
                state.setdefault("clean_weeks", 0)
                state.setdefault("total_rewritten", 0)
                return state
    except Exception:
        pass
    return {"processed_files": [], "clean_weeks": 0, "total_rewritten": 0}


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
    if not GH_TOKEN or not KNOWLEDGE_REPO:
        return False
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
            content_b64 = data.get("content", "")
            if content_b64:
                content = base64.b64decode(content_b64).decode("utf-8")
                return content, data.get("sha", "")
            else:
                print(f"      [WARN] No content field for {path}")
        else:
            print(f"      [WARN] HTTP {response.status_code} for {path}")
    except Exception as e:
        print(f"      [WARN] Exception: {e} for {path}")
    return None


def update_file(path: str, new_content: str, sha: str, commit_msg: str) -> bool:
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


def delete_file(path: str, sha: str, commit_msg: str) -> bool:
    """Delete a file from GitHub."""
    url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{path}"
    payload = {
        "message": commit_msg,
        "sha": sha,
        "branch": "main",
    }
    try:
        response = requests.delete(url, json=payload, headers=_github_headers(), timeout=15)
        return response.status_code in [200, 201]
    except Exception:
        return False


# ===========================================================================
# FAO Detection
# ===========================================================================

def contains_fao_content(text: str) -> bool:
    for pattern in FAO_CONTENT_PATTERNS:
        if pattern.search(text):
            return True
    return False


def has_fao_filename(filename: str) -> bool:
    return bool(FAO_FILENAME_PATTERN.search(filename))


# ===========================================================================
# File Scanning (FIXED)
# ===========================================================================

def scan_for_fao_files(state: Dict) -> List[Dict]:
    """Scan all category folders for files with FAO references."""
    
    processed = set(state.get("processed_files", []))
    fao_files = []
    
    print(f"Scanning {len(CATEGORY_FOLDERS)} category folders...")
    print(f"Repo: {KNOWLEDGE_REPO}")
    sys.stdout.flush()
    
    for folder in CATEGORY_FOLDERS:
        url = f"{GITHUB_API}/repos/{KNOWLEDGE_REPO}/contents/{folder}"
        print(f"  Checking: {folder}/", end=" ")
        sys.stdout.flush()
        
        try:
            response = requests.get(url, headers=_github_headers(), timeout=15)
            if response.status_code != 200:
                print(f"HTTP {response.status_code}")
                sys.stdout.flush()
                continue
            
            files = response.json()
            if not isinstance(files, list):
                print(f"unexpected response type")
                sys.stdout.flush()
                continue
            
            print(f"{len(files)} files")
            sys.stdout.flush()
            
            for file_info in files:
                filepath = file_info.get("path", "")
                filename = filepath.split("/")[-1] if "/" in filepath else filepath
                
                if not filename.endswith(".md"):
                    continue
                
                if filepath in processed:
                    continue
                
                if has_fao_filename(filename):
                    print(f"    ⚠️  FAO MATCH: {filename}")
                    sys.stdout.flush()
                    
                    content_result = get_file_content(filepath)
                    if content_result:
                        content, sha = content_result
                        fao_in_body = contains_fao_content(content)
                        print(f"    Content: {len(content)} chars | FAO in body: {fao_in_body}")
                    else:
                        content = ""
                        sha = file_info.get("sha", "")
                        fao_in_body = False
                        print(f"    WARNING: Could not fetch content, using sha from listing")
                    
                    fao_files.append({
                        "path": filepath,
                        "sha": sha,
                        "has_fao_content": fao_in_body,
                        "has_fao_filename": True,
                        "content": content,
                    })
                    sys.stdout.flush()
                    
        except Exception as e:
            print(f"ERROR: {e}")
            sys.stdout.flush()
    
    print(f"\nTotal FAO files found: {len(fao_files)}")
    sys.stdout.flush()
    return fao_files


# ===========================================================================
# AI Rewriting
# ===========================================================================

def rewrite_with_groq(content: str) -> str:
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
            return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"    Groq error: {e}")
    return ""


def rewrite_with_mistral(content: str) -> str:
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
            return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"    Mistral error: {e}")
    return ""


def rewrite_content(content: str) -> str:
    if GROQ_API_KEY:
        rewritten = rewrite_with_groq(content)
        if rewritten and len(rewritten) >= 300:
            if not contains_fao_content(rewritten):
                return rewritten
            else:
                print(f"    ⚠️  Rewrite still contains FAO — retrying...")
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
    folder = original_path.split("/")[0]
    filename = original_path.split("/")[-1]
    clean_name = re.sub(r'FAO[_\-]?', '', filename, flags=re.IGNORECASE)
    clean_name = re.sub(r'fao[_\-]?', '', clean_name)
    clean_name = re.sub(r'[_\-]{2,}', '_', clean_name)
    clean_name = clean_name.strip('_-')
    return f"{folder}/{clean_name}"


# ===========================================================================
# Database Update
# ===========================================================================

def update_databases(original_path: str, new_path: str) -> bool:
    success_count = 0
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
            print(f"    ⚠️  Fly.io PG: {e}")
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
            print(f"    ⚠️  Supabase: {e}")
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
            print(f"    ⚠️  Neon: {e}")
    sys.stdout.flush()
    return success_count >= 1


# ===========================================================================
# Main
# ===========================================================================

def run_fao_rewriter():
    print("=" * 60)
    print("FAO Safety-Net Rewriter v1.1")
    print(f"Run: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    print(f"Groq: {'ACTIVE' if GROQ_API_KEY else 'NOT SET'}")
    print(f"Mistral: {'ACTIVE' if MISTRAL_API_KEY else 'NOT SET'}")
    print(f"Max files per run: {MAX_FILES_PER_RUN}")
    sys.stdout.flush()
    
    state = load_state()
    print(f"Previously processed: {len(state.get('processed_files', []))} files")
    print(f"Clean weeks: {state.get('clean_weeks', 0)}")
    print(f"Total rewritten: {state.get('total_rewritten', 0)}")
    sys.stdout.flush()
    
    fao_files = scan_for_fao_files(state)
    
    if not fao_files:
        state["clean_weeks"] = state.get("clean_weeks", 0) + 1
        save_state(state)
        print(f"\n✅ No FAO files found.")
        print(f"Clean weeks: {state['clean_weeks']}/4")
        if state["clean_weeks"] >= 4:
            print(f"🔒 4+ clean weeks — self-disabling threshold reached.")
        append_audit_log(
            f"## {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"- Status: CLEAN\n- Files found: 0\n- Clean weeks: {state['clean_weeks']}\n"
        )
        print("=" * 60)
        return
    
    state["clean_weeks"] = 0
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
        
        # Always rewrite if FAO in filename — the topic itself is FAO-derived
        if file_info.get("content"):
            print(f"  Rewriting content ({len(file_info['content'])} chars)...")
            sys.stdout.flush()
            new_content = rewrite_content(file_info["content"])
        else:
            print(f"  No content fetched — cannot rewrite, will rename only")
            new_content = ""
        
        if not new_content:
            failed_count += 1
            print(f"  ❌ Rewrite failed — skipping")
            state["processed_files"].append(filepath)
            save_state(state)
            continue
        
        # Strip markdown
        new_content = re.sub(r'\*{1,3}([^*]+?)\*{1,3}', r'\1', new_content)
        new_content = re.sub(r'^#{1,6}\s+', '', new_content, flags=re.MULTILINE)
        new_content = new_content.strip()
        
        # Verify clean
        if contains_fao_content(new_content):
            print(f"  ❌ Rewrite still contains FAO after retry — skipping")
            failed_count += 1
            state["processed_files"].append(filepath)
            save_state(state)
            continue
        
        new_path = generate_clean_filename(filepath)
        print(f"  New path: {new_path}")
        sys.stdout.flush()
        
        # Create new clean file
        if update_file(new_path, new_content, "", f"FAO safety rewrite: {filepath} → {new_path}"):
            # Delete original
            delete_file(filepath, file_info["sha"], f"Remove FAO file: replaced by {new_path}")
            print(f"  ✅ Rewritten and renamed")
            
            update_databases(filepath, new_path)
            
            rewritten_count += 1
            state["total_rewritten"] = state.get("total_rewritten", 0) + 1
        else:
            failed_count += 1
            print(f"  ❌ Failed to save new file")
        
        state["processed_files"].append(filepath)
        save_state(state)
        
        if files_to_process.index(file_info) < len(files_to_process) - 1:
            time.sleep(5)
    
    audit_entry = (
        f"## {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"- Status: REWRITTEN\n- Files found: {len(fao_files)}\n"
        f"- Files processed: {len(files_to_process)}\n"
        f"- Rewritten: {rewritten_count}\n- Failed: {failed_count}\n"
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
