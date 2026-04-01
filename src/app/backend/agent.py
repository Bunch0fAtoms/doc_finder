# backend/agent.py
"""
Chat agent using Foundation Model API (databricks-claude-sonnet-4-6).
Hybrid search: Vector Search for semantic queries + SQL keyword search
for exact identifiers (SKUs, part numbers, regulatory codes).
"""
import json
import os
import re
from openai import OpenAI
from databricks.sdk.core import Config
from backend.vector_search import search_documents
from backend.keyword_search import search_by_keyword

MODEL = os.getenv("FOUNDATION_MODEL", "databricks-claude-sonnet-4-6")

SYSTEM_PROMPT = """You are a document finder assistant for Integra LifeSciences.
Your job is to help employees find the right document from the company's document library.

You will receive search results from two sources:
- **Semantic search**: matches based on meaning and topic similarity
- **Keyword search**: exact text matches for specific codes, SKUs, part numbers, etc.

Based on the combined results:
1. Recommend the best matching document
2. Explain briefly why it matches their request
3. If keyword matches exist, prioritize those for identifier-based queries
4. Include the exact filename in your response

If the user asks to refine or says "not that one", look at the search results for alternatives.

IMPORTANT: Always include a JSON block at the end of your response in this exact format:
```json
{"filename": "the_matched_file.pdf", "score": 0.85}
```
If no good match was found, set filename to null."""

# Pattern to detect likely identifiers: alphanumeric codes, SKUs, part numbers
IDENTIFIER_PATTERN = re.compile(
    r'\b[A-Z]{1,5}[-]?\d{3,}[A-Z]?\b'  # K243531, SKU-12345, 882.5550
    r'|\b\d{2,3}\.\d{4}\b'              # CFR numbers like 882.5550
    r'|\b[A-Z]{2,}\d{2,}\b'             # JXG, XR7890
)


def _get_openai_client() -> OpenAI:
    cfg = Config()
    token = cfg.authenticate()["Authorization"].replace("Bearer ", "")
    return OpenAI(
        api_key=token,
        base_url=f"{cfg.host}/serving-endpoints",
    )


def _extract_identifiers(message: str) -> list[str]:
    """Extract likely identifiers (SKUs, codes, part numbers) from the message."""
    return IDENTIFIER_PATTERN.findall(message)


def _deduplicate_results(results: list[dict]) -> list[dict]:
    """Deduplicate by filename, keeping the entry with the highest score."""
    seen = {}
    for r in results:
        fname = r["filename"]
        if fname not in seen or r.get("score", 0) > seen[fname].get("score", 0):
            seen[fname] = r
    return list(seen.values())


def chat(message: str, history: list[dict]) -> dict:
    """
    Process a chat message using hybrid search (semantic + keyword).
    """
    client = _get_openai_client()

    # Always run semantic search
    semantic_results = search_documents(message)

    # Run keyword search if identifiers are detected
    identifiers = _extract_identifiers(message)
    keyword_results = []
    for ident in identifiers:
        keyword_results.extend(search_by_keyword(ident))

    # Merge and deduplicate
    all_results = _deduplicate_results(keyword_results + semantic_results)

    # Build search context for the LLM
    search_sections = []
    if keyword_results:
        search_sections.append(
            f"Keyword matches (exact text match for: {', '.join(identifiers)}):\n"
            + json.dumps(keyword_results, indent=2)
        )
    if semantic_results:
        search_sections.append(
            "Semantic matches (topic similarity):\n"
            + json.dumps(semantic_results, indent=2)
        )
    search_context = "\n\n".join(search_sections) if search_sections else "No results found."

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({
        "role": "user",
        "content": f"{message}\n\n---\nSearch results from document library:\n{search_context}",
    })

    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=1024,
    )

    content = response.choices[0].message.content or ""

    # Extract structured metadata from response
    filename = None
    score = None
    try:
        json_start = content.rfind("```json")
        json_end = content.rfind("```", json_start + 7)
        if json_start != -1 and json_end != -1:
            json_str = content[json_start + 7 : json_end].strip()
            meta = json.loads(json_str)
            filename = meta.get("filename")
            score = meta.get("score")
    except (json.JSONDecodeError, ValueError):
        pass

    return {"response": content, "filename": filename, "score": score}
