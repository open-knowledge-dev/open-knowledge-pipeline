"""Prompt templates for Cloudflare Workers AI scrapers.
10 prompt styles including comparisons — same variety as Groq scrapers."""

PROMPTS = [
    # Style 1: Comprehensive overview
    """Write a detailed, factual article about {topic} in the context of Ghana and Africa. 
Include historical background, current significance, and cultural relevance. 
Write in an authoritative, educational tone. Minimum 500 words.""",
    
    # Style 2: Cultural deep dive
    """Explain {topic} as it relates to Ghanaian or African traditions, practices, 
or knowledge systems. Be thorough, accurate, and culturally informed. 
Include specific examples where possible. Minimum 500 words.""",
    
    # Style 3: Historical perspective
    """Provide a historical overview of {topic}, tracing its origins and development 
in Ghana and across Africa. Highlight key events, figures, and turning points. 
Minimum 500 words.""",
    
    # Style 4: Modern relevance
    """Discuss {topic} in contemporary Ghana and Africa. How has this evolved? 
What is its relevance today? Connect traditional knowledge to modern applications. 
Minimum 500 words.""",
    
    # Style 5: Regional comparison
    """Compare and contrast how {topic} manifests in Ghana versus other West African 
countries. What are the similarities and unique differences? Minimum 500 words.""",
    
    # Style 6: Practical guide
    """Write a detailed, practical guide about {topic} as practiced or understood 
in Ghana and Africa. Include processes, methods, or frameworks where applicable. 
Minimum 500 words.""",
    
    # Style 7: Storytelling approach
    """Tell the story of {topic} through a narrative lens rooted in Ghanaian or 
African experience. Use vivid descriptions and cultural context to bring the 
subject to life while remaining factually accurate. Minimum 500 words.""",
    
    # Style 8: Wisdom and philosophy
    """Explore the deeper meaning and philosophical underpinnings of {topic} in 
African thought and Ghanaian traditions. What wisdom does this subject hold? 
What can the world learn from it? Minimum 500 words.""",
    
    # Style 9: Question and answer
    """Answer the following questions about {topic} in the Ghanaian and African 
context: What is it? Where did it come from? Why does it matter? How is it 
practiced or understood today? What is its future? Minimum 500 words.""",
    
    # Style 10: Academic perspective
    """Write a scholarly overview of {topic} focusing on Ghana and Africa. 
Include relevant terminology, classifications, and frameworks. Reference 
traditional knowledge systems and academic perspectives. Minimum 500 words.""",
]
