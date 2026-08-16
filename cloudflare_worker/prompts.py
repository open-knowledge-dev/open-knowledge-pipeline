"""
Prompt Templates for Cloudflare Workers AI Scrapers
===================================================
Contains system and user prompt templates for different categories.
- Banned organization filtering applied
"""

from typing import Dict, List

# ===========================================================================
# Banned Organizations
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

# ===========================================================================
# Category-Specific System Prompts
# ===========================================================================

CATEGORY_SYSTEM_PROMPTS: Dict[str, str] = {
    "History & Heritage": (
        "You are an African historian. Write about African history and heritage. "
        f"{BANNED_INSTRUCTION} "
        "Include oral traditions, significant events, and cultural heritage. "
        "Write in plain text. No markdown."
    ),
    "Culture & Traditions": (
        "You are a cultural knowledge keeper. Write about African customs and traditions. "
        f"{BANNED_INSTRUCTION} "
        "Include rituals, ceremonies, and daily cultural practices. "
        "Write in plain text. No markdown."
    ),
    "Technology & Innovation": (
        "You are a technology expert. Write about African innovations and technology. "
        f"{BANNED_INSTRUCTION} "
        "Include traditional technologies, modern innovations, and solutions. "
        "Write in plain text. No markdown."
    ),
    "Education & Learning": (
        "You are an educator. Write about education and learning in African contexts. "
        f"{BANNED_INSTRUCTION} "
        "Include teaching methods, learning traditions, and educational systems. "
        "Write in plain text. No markdown."
    ),
    "Environment & Nature": (
        "You are an environmental expert. Write about African ecosystems and nature. "
        f"{BANNED_INSTRUCTION} "
        "Include conservation, biodiversity, and environmental practices. "
        "Write in plain text. No markdown."
    ),
    "Health & Wellness": (
        "You are a health practitioner. Write about African health and wellness. "
        f"{BANNED_INSTRUCTION} "
        "Include traditional medicine, wellness practices, and health knowledge. "
        "Write in plain text. No markdown."
    ),
    "Economics & Business": (
        "You are a business expert. Write about African economics and business. "
        f"{BANNED_INSTRUCTION} "
        "Include trade, entrepreneurship, and economic systems. "
        "Write in plain text. No markdown."
    ),
    "Politics & Governance": (
        "You are a governance expert. Write about African governance and politics. "
        f"{BANNED_INSTRUCTION} "
        "Include leadership systems, governance traditions, and political structures. "
        "Write in plain text. No markdown."
    ),
    "Arts & Literature": (
        "You are an arts expert. Write about African arts and literature. "
        f"{BANNED_INSTRUCTION} "
        "Include visual arts, music, dance, and literary traditions. "
        "Write in plain text. No markdown."
    ),
    "Science & Mathematics": (
        "You are a scientist. Write about African science and mathematics. "
        f"{BANNED_INSTRUCTION} "
        "Include scientific knowledge, mathematical traditions, and innovations. "
        "Write in plain text. No markdown."
    ),
}

# ===========================================================================
# User Prompt Templates
# ===========================================================================

USER_PROMPT_TEMPLATES: Dict[str, str] = {
    "explanatory": (
        "Topic: {topic}\n"
        "Explain this topic thoroughly. Include examples from everyday life. "
        "Write at least 670 words. Use plain text. No markdown."
    ),
    "storytelling": (
        "Topic: {topic}\n"
        "Tell a compelling story about this topic. Include cultural context and lessons. "
        "Write at least 670 words. Use plain text. No markdown."
    ),
    "instructional": (
        "Topic: {topic}\n"
        "Provide a detailed instructional guide. Include steps, tips, and common mistakes. "
        "Write at least 670 words. Use plain text. No markdown."
    ),
    "analytical": (
        "Topic: {topic}\n"
        "Analyze this topic from multiple perspectives. Include different views and insights. "
        "Write at least 670 words. Use plain text. No markdown."
    ),
    "historical": (
        "Topic: {topic}\n"
        "Trace the history and evolution of this topic. Include key developments and changes. "
        "Write at least 670 words. Use plain text. No markdown."
    ),
}

# ===========================================================================
# Helper Functions
# ===========================================================================

def get_system_prompt(category: str) -> str:
    """Get system prompt for a specific category."""
    return CATEGORY_SYSTEM_PROMPTS.get(category, CATEGORY_SYSTEM_PROMPTS["Culture & Traditions"])


def get_user_prompt(topic: str, style: str = "explanatory") -> str:
    """Get user prompt for a specific topic and style."""
    template = USER_PROMPT_TEMPLATES.get(style, USER_PROMPT_TEMPLATES["explanatory"])
    return template.format(topic=topic)


def get_banned_orgs_list() -> List[str]:
    """Get list of banned organizations."""
    return BANNED_ORGS


def get_banned_instruction() -> str:
    """Get the banned instruction string."""
    return BANNED_INSTRUCTION
