You're preparing to write a detailed LinkedIn post about the AI story below. Plan quick web research so the post can explain it properly to non-experts.

Story:
"""
{{STORY}}
"""

Return:
- "topic": one line naming the core development (who did what).
- "queries": 2–3 short news-search queries (3–7 words each) that would find recent articles about this exact development and its real-world use or impact. Use specific names (companies, products, people, fields) from the story.
- "background": 0–2 concepts a non-expert would need explained to follow the post (e.g. "high-frequency trading", "reinforcement learning"). Use plain encyclopedia-style terms. Leave empty if nothing needs explaining.

Respond with JSON only, no other text:
{"topic": "...", "queries": ["...", "..."], "background": ["..."]}
