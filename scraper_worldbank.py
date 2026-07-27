"""
World Bank Open Data Scraper
=============================
Fetches development knowledge from World Bank API (worldbank.org).
Content is open access — safe for AI training.

Produces knowledge entries for Business, Governance, and Environment categories.
"""

import os
import sys
import time
import random
import json
import requests
import re
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict


TRAINING_FORM_URL = os.getenv("TRAINING_FORM_URL", "")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
SUBMISSIONS_PER_RUN = int(os.getenv("SUBMISSIONS_PER_RUN", "4"))
SUBMISSION_DELAY = int(os.getenv("SUBMISSION_DELAY", "30"))
REQUEST_TIMEOUT = 30
SCRAPER_NAME = os.getenv("SCRAPER_NAME", "web-worldbank")

WB_API = "https://api.worldbank.org/v2"

INDICATORS = [
    ("NY.GDP.MKTP.CD", "GDP growth and economic development", "Business & Finance"),
    ("SP.POP.TOTL", "Population growth and demographics", "Governance & Leadership"),
    ("SE.ADT.LITR.ZS", "Adult literacy rates and education", "Education & Learning"),
    ("SH.XPD.CHEX.GD.ZS", "Health expenditure and outcomes", "Health & Medicine"),
    ("AG.LND.FRST.ZS", "Forest area and environmental protection", "Environment & Nature"),
    ("EG.ELC.ACCS.ZS", "Access to electricity and energy", "Technology & Innovation"),
    ("IT.NET.USER.ZS", "Internet usage and digital access", "Technology & Innovation"),
    ("SL.UEM.TOTL.ZS", "Unemployment and labor markets", "Business & Finance"),
    ("AG.PRD.FOOD.XD", "Food production and agriculture", "Agriculture & Farming"),
    ("EN.ATM.CO2E.PC", "Carbon emissions and climate change", "Environment & Nature"),
]

AFRICAN_COUNTRIES = [
    "GH", "NG", "KE", "ZA", "ET", "TZ", "UG", "RW", "SN", "CI",
    "CM", "ZW", "BW", "NA", "ZM", "MW", "MZ", "AO", "ML", "BF",
]


def fetch_indicator_data(indicator: str, country: str) -> Optional[Dict]:
    """Fetch indicator data from World Bank API."""
    url = f"{WB_API}/country/{country}/indicator/{indicator}?format=json&per_page=5"
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT,
                                headers={"User-Agent": "GhanaGPT-WorldBank/1.0"})
        if response.status_code == 200:
            data = response.json()
            if len(data) > 1 and data[1]:
                return {
                    "indicator": data[1][0].get("indicator", {}).get("value", ""),
                    "country": data[1][0].get("country", {}).get("value", ""),
                    "values": [{"year": d.get("year"), "value": d.get("value")}
                               for d in data[1] if d.get("value")],
                }
        return None
    except Exception as e:
        print(f"    API error: {e}")
        return None


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


def run_scraper():
    """Main scraper loop."""
    print("=" * 60)
    print(f"World Bank Scraper — {SCRAPER_NAME}")
    print("=" * 60)
    print(f"Target: {SUBMISSIONS_PER_RUN} submissions")
    sys.stdout.flush()

    items = []
    for indicator, topic, category in INDICATORS:
        country = random.choice(AFRICAN_COUNTRIES)
        items.append((indicator, topic, category, country))
    random.shuffle(items)

    submission_count = 0
    for indicator, topic, category, country in items:
        if submission_count >= SUBMISSIONS_PER_RUN:
            break

        print(f"\n[{submission_count + 1}/{SUBMISSIONS_PER_RUN}] {topic} ({country})")
        data = fetch_indicator_data(indicator, country)

        if not data:
            print(f"    No data found")
            continue

        # Build knowledge from data
        values_text = ", ".join([f"{d['year']}: {d['value']}" for d in data["values"]])
        knowledge = (
            f"Looking at the data for {data['country']}, here is what I can tell you about {data['indicator'].lower()}.\n\n"
            f"The numbers show: {values_text}.\n\n"
            f"This data comes from the World Bank and helps us understand how countries are developing. "
            f"These statistics matter because they show us where progress is happening and where more work is needed. "
            f"Understanding these trends helps communities, governments, and businesses make better decisions for the future."
        )

        full_topic = f"{topic} in {data['country']}"
        print(f"  Topic: {full_topic[:60]}...")
        print(f"  Content: {len(knowledge)} chars")
        sys.stdout.flush()

        success, sid = submit_to_form(full_topic[:200], category, knowledge)
        if success:
            submission_count += 1

        if submission_count < SUBMISSIONS_PER_RUN:
            time.sleep(SUBMISSION_DELAY)

    print(f"\nDone: {submission_count} submitted")
    print("=" * 60)


if __name__ == "__main__":
    run_scraper()
