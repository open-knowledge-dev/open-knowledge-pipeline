#!/usr/bin/env python3
"""
AI Knowledge Scraper for Ghana-GPT
Generates high-quality training data from AI models
Uses Groq Llama 3.3 70B
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
from pathlib import Path

# Constants
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
BANNED_INSTRUCTION = f"IMPORTANT: Never mention or reference any of these organizations: {BANNED_ORGS_STRING}. Focus entirely on local African perspectives without any external organizational framing. Do not reference development programs, aid, or international interventions. Write from the perspective of African knowledge systems only."

# Categories and their weights
CATEGORIES = {
    "History & Heritage": {"weight": 1.0, "thin": False},
    "Culture & Traditions": {"weight": 1.0, "thin": False},
    "Technology & Innovation": {"weight": 1.0, "thin": False},
    "Education & Learning": {"weight": 1.0, "thin": False},
    "Environment & Nature": {"weight": 1.0, "thin": False},
    "Health & Wellness": {"weight": 0.8, "thin": False},
    "Economics & Business": {"weight": 0.8, "thin": True},
    "Politics & Governance": {"weight": 0.8, "thin": True},
    "Arts & Literature": {"weight": 0.6, "thin": True},
    "Science & Mathematics": {"weight": 0.6, "thin": True},
    "Philosophy & Ethics": {"weight": 0.6, "thin": True},
    "Agriculture & Food": {"weight": 0.8, "thin": True},
    "Infrastructure & Urban": {"weight": 0.6, "thin": True},
    "Energy & Resources": {"weight": 0.6, "thin": True},
    "Water & Sanitation": {"weight": 0.6, "thin": True},
    "Transport & Mobility": {"weight": 0.4, "thin": True},
    "Media & Communication": {"weight": 0.4, "thin": True},
    "Religion & Spirituality": {"weight": 0.4, "thin": True},
    "Sports & Recreation": {"weight": 0.4, "thin": True},
    "Cuisine & Gastronomy": {"weight": 0.4, "thin": True}
}

PROMPT_STYLES = [
    "narrative", "explanatory", "analytical", "descriptive",
    "comparative", "argumentative", "historical", "scientific",
    "storytelling", "instructional"
]

# Weight compare-contrast more heavily
PROMPT_STYLE_WEIGHTS = {
    "narrative": 1.0,
    "explanatory": 1.0,
    "analytical": 1.5,
    "descriptive": 1.0,
    "comparative": 2.0,
    "argumentative": 1.0,
    "historical": 1.0,
    "scientific": 1.0,
    "storytelling": 1.0,
    "instructional": 1.0
}

LANGUAGES = [
    "English", "French", "Portuguese", "Arabic", "Swahili"
]
LANGUAGE_WEIGHTS = [0.7, 0.1, 0.1, 0.05, 0.05]

MIN_WORDS = 670

class AIKnowledgeScraper:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = "llama-3.3-70b-versatile"
        self.training_form_url = os.getenv("TRAINING_FORM_URL", "https://training.ghana-gpt.com")
        self.scraper_key = os.getenv("SCRAPER_API_KEY")
        
        self.state_file = "scraper_state.json"
        self.state = self._load_state()
        
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })

    def _load_state(self) -> Dict:
        """Load state from file"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except:
                return {"topics_seen": [], "topics_rejected": [], "last_run": None}
        return {"topics_seen": [], "topics_rejected": [], "last_run": None}

    def _save_state(self):
        """Save state to file"""
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f)

    def _get_topic_weights(self) -> Dict[str, float]:
        """Calculate weights for each category based on thin status and history"""
        weights = {}
        for cat, info in CATEGORIES.items():
            base = info["weight"]
            if info["thin"]:
                base *= 1.5  # Boost thin categories
            # Check if we've seen too many from this category
            seen_count = len([t for t in self.state["topics_seen"] if t.get("category") == cat])
            if seen_count > 50:
                base *= 0.8
            weights[cat] = base
        return weights

    def _select_category(self) -> str:
        """Select a category based on weights"""
        weights = self._get_topic_weights()
        total = sum(weights.values())
        r = random.random() * total
        for cat, weight in weights.items():
            r -= weight
            if r <= 0:
                return cat
        return list(CATEGORIES.keys())[0]

    def _get_topic_pool(self, category: str, count: int = 25) -> List[str]:
        """Get a batch of topics from the API"""
        system_prompt = f"""You are an African knowledge system expert. Generate {count} specific, distinct, and interesting topics related to {category} in Africa.
        
Rules:
1. Topics should be specific enough to generate 670+ words of content
2. Topics must focus on African knowledge, perspectives, and systems
3. Topics should cover different regions, time periods, and approaches
4. Each topic must be 3-8 words long
5. Topics should be educational and valuable for AI training
6. Do NOT include topics that would mention {BANNED_ORGS_STRING}
7. Focus on indigenous knowledge, local innovations, and authentic African perspectives

Return only a JSON array of topic strings."""
        
        response = self._call_api(system_prompt, f"Generate {count} topics on {category}", 2000)
        try:
            topics = json.loads(response)
            if isinstance(topics, list):
                return topics[:count]
        except:
            # Fallback: try to extract JSON from response
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
        """Make API call to Groq"""
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

    def _generate_content(self, topic: str, category: str, style: str, language: str) -> Optional[str]:
        """Generate content for a topic"""
        style_desc = {
            "narrative": "Tell a story about this topic",
            "explanatory": "Explain this topic in detail",
            "analytical": "Analyze this topic from multiple angles",
            "descriptive": "Describe this topic with rich detail",
            "comparative": "Compare different aspects or examples of this topic",
            "argumentative": "Present a reasoned argument about this topic",
            "historical": "Trace the historical development of this topic",
            "scientific": "Present the scientific or technical aspects of this topic",
            "storytelling": "Tell a compelling story around this topic",
            "instructional": "Provide instructional content about this topic"
        }
        
        style_prompt = style_desc.get(style, "Write about this topic")
        
        system_prompt = f"""You are an African knowledge system expert. Write high-quality, educational content in {language} about {topic}.
        
Guidelines:
1. Content must be at least {MIN_WORDS} words
2. Focus on African perspectives, knowledge, and context
3. Include specific details, examples, and insights
4. Content should be suitable for AI training data
5. Write in a clear, engaging, and authoritative style
6. {BANNED_INSTRUCTION}
7. Do not mention or reference international organizations, NGOs, or development programs
8. Do not use phrases like "according to", "reported by", or other attribution to external sources
9. Write as if you are sharing authentic African knowledge from within the community
10. Include practical applications, historical context, and cultural relevance

Style: {style_prompt}

Important: All content must be original, factual, and representative of African knowledge systems. Do not copy or paraphrase from existing sources."""
        
        user_prompt = f"Write a comprehensive piece about {topic} in {category}. Style: {style}. Language: {language}"
        
        content = self._call_api(system_prompt, user_prompt, 8000)
        
        # Verify minimum length and check for banned orgs
        word_count = len(content.split())
        if word_count < MIN_WORDS:
            return None
        
        # Check for banned organizations
        content_lower = content.lower()
        for org in BANNED_ORGS:
            if org.lower() in content_lower:
                print(f"Content contains banned organization: {org}")
                return None
        
        # Check for international development language
        dev_terms = ["development program", "aid program", "international assistance", 
                    "foreign aid", "development agency", "grant", "funding", "NGO", "non-governmental"]
        for term in dev_terms:
            if term in content_lower:
                print(f"Content contains development language: {term}")
                return None
        
        return content

    def _submit_to_training_form(self, topic: str, category: str, content: str, language: str) -> bool:
        """Submit content to training form"""
        # Generate a unique ID
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        
        payload = {
            "topic": topic,
            "category": category,
            "content": content,
            "language": language,
            "source": f"ai_scraper_{self.model}",
            "verification_code": "000000",  # Will be validated by backend
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
        """Main run loop"""
        print(f"Starting AI scraper run - {max_entries} entries")
        
        entries_generated = 0
        attempts = 0
        
        while entries_generated < max_entries and attempts < max_entries * 3:
            attempts += 1
            
            # Select category
            category = self._select_category()
            print(f"Selected category: {category}")
            
            # Get topics
            topics = self._get_topic_pool(category, 25)
            if not topics:
                print("No topics generated, skipping")
                continue
            
            # Filter out seen topics
            seen_topics = set([t.get("topic") for t in self.state["topics_seen"] if isinstance(t, dict)])
            new_topics = [t for t in topics if t not in seen_topics]
            
            if not new_topics:
                print("All topics seen, selecting random topic")
                # Select a random unseen topic
                import random
                for t in topics:
                    if t not in seen_topics:
                        new_topics = [t]
                        break
                if not new_topics:
                    continue
            
            # Select a topic
            topic = random.choice(new_topics)
            
            # Select style with weighting
            styles = list(PROMPT_STYLE_WEIGHTS.keys())
            style_weights = [PROMPT_STYLE_WEIGHTS[s] for s in styles]
            style = random.choices(styles, weights=style_weights, k=1)[0]
            
            # Select language
            language = random.choices(LANGUAGES, weights=LANGUAGE_WEIGHTS, k=1)[0]
            
            print(f"Generating content for: {topic} ({style}, {language})")
            
            content = self._generate_content(topic, category, style, language)
            if not content:
                print(f"Failed to generate content for {topic}")
                self.state["topics_rejected"].append({"topic": topic, "reason": "generation_failed"})
                self._save_state()
                continue
            
            # Submit to training form
            if self._submit_to_training_form(topic, category, content, language):
                entries_generated += 1
                self.state["topics_seen"].append({
                    "topic": topic,
                    "category": category,
                    "timestamp": datetime.now().isoformat()
                })
                self._save_state()
                print(f"Successfully submitted: {topic} ({entries_generated}/{max_entries})")
            else:
                print(f"Failed to submit {topic}")
                self.state["topics_rejected"].append({"topic": topic, "reason": "submission_failed"})
                self._save_state()
            
            # Rate limiting
            time.sleep(0.5)
        
        self.state["last_run"] = datetime.now().isoformat()
        self._save_state()
        print(f"Run complete. Generated {entries_generated} entries.")

if __name__ == "__main__":
    max_entries = int(os.getenv("MAX_ENTRIES", "10"))
    scraper = AIKnowledgeScraper()
    scraper.run(max_entries)
