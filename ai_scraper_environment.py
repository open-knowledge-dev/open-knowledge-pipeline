#!/usr/bin/env python3
"""
Environment & Nature AI Scraper for Ghana-GPT
Specialized scraper for environmental knowledge
"""

import os
import sys
import json
import hashlib
import random
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
import requests

# Constants
BANNED_ORGS = [
    "FAO", "Food and Agriculture Organization", "WHO", "World Health Organization",
    "UN", "United Nations", "World Bank", "IMF", "International Monetary Fund",
    "UNDP", "UNESCO", "UNICEF", "USAID", "DFID", "GIZ",
    "World Food Programme", "WFP", "International Labour Organization", "ILO",
    "World Trade Organization", "WTO", "African Development Bank", "AfDB",
    "European Union", "EU"
]

BANNED_ORGS_STRING = ", ".join(BANNED_ORGS)
BANNED_INSTRUCTION = f"IMPORTANT: Never mention or reference any of these organizations: {BANNED_ORGS_STRING}. Focus entirely on African environmental knowledge, indigenous ecological practices, and local perspectives."

# Environment categories
ENV_SUBCATEGORIES = [
    "Ecosystems & Biodiversity",
    "Climate & Weather Patterns",
    "Traditional Ecological Knowledge",
    "Indigenous Conservation Practices",
    "Water Resources Management",
    "Soil & Agriculture Systems",
    "Forest & Woodland Management",
    "Savanna & Grassland Ecology",
    "Coastal & Marine Environments",
    "Wildlife & Habitats",
    "Traditional Medicine & Plants",
    "Sustainable Resource Use",
    "Seasonal Cycles & Calendars",
    "Natural Disaster Preparedness",
    "Fire Management Practices"
]

LANGUAGES = ["English", "French", "Portuguese", "Arabic", "Swahili"]
LANGUAGE_WEIGHTS = [0.7, 0.1, 0.1, 0.05, 0.05]
MIN_WORDS = 670

class EnvironmentScraper:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = "llama-3.3-70b-versatile"
        self.training_form_url = os.getenv("TRAINING_FORM_URL", "https://training.ghana-gpt.com")
        self.scraper_key = os.getenv("SCRAPER_API_KEY")
        
        self.state_file = "environment_scraper_state.json"
        self.state = self._load_state()
        
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })

    def _load_state(self) -> Dict:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except:
                return {"topics_seen": [], "topics_rejected": [], "last_run": None}
        return {"topics_seen": [], "topics_rejected": [], "last_run": None}

    def _save_state(self):
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f)

    def _select_subcategory(self) -> str:
        return random.choice(ENV_SUBCATEGORIES)

    def _get_topic_pool(self, subcategory: str, count: int = 25) -> List[str]:
        system_prompt = f"""You are an African environmental knowledge expert. Generate {count} specific topics related to {subcategory} in Africa.

Rules:
1. Focus on indigenous and local African environmental knowledge
2. {BANNED_INSTRUCTION}
3. Topics should be educational and suitable for AI training
4. Each topic should be 3-8 words
5. Return only a JSON array of topic strings"""
        
        response = self._call_api(system_prompt, f"Generate {count} environmental topics on {subcategory}", 2000)
        try:
            topics = json.loads(response)
            if isinstance(topics, list):
                return topics[:count]
        except:
            import re
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                try:
                    topics = json.loads(match.group())
                    if isinstance(topics, list):
                        return topics[:count]
                except:
                    pass
        return []

    def _call_api(self, system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.8
        }
        
        try:
            response = self.session.post(self.base_url, json=payload)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"API call failed: {e}")
            return ""

    def _generate_content(self, topic: str, subcategory: str, language: str) -> Optional[str]:
        system_prompt = f"""You are an African environmental knowledge expert. Write educational content in {language} about {topic}.

Guidelines:
1. Content must be at least {MIN_WORDS} words
2. Focus on African environmental knowledge, indigenous practices, and local perspectives
3. {BANNED_INSTRUCTION}
4. Do not mention international environmental organizations or development programs
5. Include practical applications and traditional knowledge
6. Write from the perspective of local communities

Write a comprehensive, original piece."""
        
        user_prompt = f"Write about {topic} in {subcategory}. Language: {language}"
        
        content = self._call_api(system_prompt, user_prompt, 8000)
        
        word_count = len(content.split())
        if word_count < MIN_WORDS:
            return None
        
        content_lower = content.lower()
        for org in BANNED_ORGS:
            if org.lower() in content_lower:
                return None
        
        dev_terms = ["development program", "aid", "international assistance", 
                    "foreign aid", "grant", "funding", "NGO"]
        for term in dev_terms:
            if term in content_lower:
                return None
        
        return content

    def _submit_to_training_form(self, topic: str, category: str, content: str, language: str) -> bool:
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        
        payload = {
            "topic": topic,
            "category": f"Environment & Nature - {category}",
            "content": content,
            "language": language,
            "source": f"ai_scraper_environment_{self.model}",
            "verification_code": "000000",
            "scraper_key": self.scraper_key,
            "content_hash": content_hash
        }
        
        try:
            response = self.session.post(
                f"{self.training_form_url}/api/submit",
                json=payload,
                headers={"X-Scraper-Key": self.scraper_key}
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Submission failed: {e}")
            return False

    def run(self, max_entries: int = 10):
        print(f"Starting Environment scraper - {max_entries} entries")
        
        entries_generated = 0
        attempts = 0
        
        while entries_generated < max_entries and attempts < max_entries * 3:
            attempts += 1
            
            subcategory = self._select_subcategory()
            print(f"Selected subcategory: {subcategory}")
            
            topics = self._get_topic_pool(subcategory, 25)
            if not topics:
                continue
            
            seen_topics = set([t.get("topic") for t in self.state["topics_seen"] if isinstance(t, dict)])
            new_topics = [t for t in topics if t not in seen_topics]
            
            if not new_topics:
                for t in topics:
                    if t not in seen_topics:
                        new_topics = [t]
                        break
                if not new_topics:
                    continue
            
            topic = random.choice(new_topics)
            language = random.choices(LANGUAGES, weights=LANGUAGE_WEIGHTS, k=1)[0]
            
            print(f"Generating content for: {topic} ({language})")
            
            content = self._generate_content(topic, subcategory, language)
            if not content:
                self.state["topics_rejected"].append({"topic": topic, "reason": "generation_failed"})
                self._save_state()
                continue
            
            if self._submit_to_training_form(topic, subcategory, content, language):
                entries_generated += 1
                self.state["topics_seen"].append({
                    "topic": topic,
                    "category": subcategory,
                    "timestamp": datetime.now().isoformat()
                })
                self._save_state()
                print(f"Successfully submitted: {topic} ({entries_generated}/{max_entries})")
            else:
                self.state["topics_rejected"].append({"topic": topic, "reason": "submission_failed"})
                self._save_state()
            
            time.sleep(0.5)
        
        self.state["last_run"] = datetime.now().isoformat()
        self._save_state()
        print(f"Run complete. Generated {entries_generated} entries.")

if __name__ == "__main__":
    max_entries = int(os.getenv("MAX_ENTRIES", "10"))
    scraper = EnvironmentScraper()
    scraper.run(max_entries)
