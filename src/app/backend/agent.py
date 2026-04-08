# backend/agent.py
"""
Chat agent using Foundation Model API (databricks-claude-sonnet-4-6).
Hybrid search: Vector Search for semantic queries + SQL keyword search
for exact identifiers. Gemini 2.5 Pro classifies queries and extracts
search terms, replacing brittle regex detection.
"""
import json
import os
from openai import OpenAI
from databricks.sdk.core import Config
from backend.vector_search import search_documents
from backend.keyword_search import search_by_keyword

MODEL = os.getenv("FOUNDATION_MODEL", "databricks-claude-sonnet-4-6")
CLASSIFIER_MODEL = "databricks-gemini-2-5-pro"

SYSTEM_PROMPT = """You are a document finder assistant for Integra LifeSciences.
Your job is to help employees find the right document from the company's document library.

You will receive search results from two sources:
- **Semantic search**: matches based on meaning and topic similarity
- **Keyword search**: exact text matches for specific codes, SKUs, part numbers, etc.

You will also receive a query analysis explaining how the search was interpreted.

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

CLASSIFIER_PROMPT = """You are a query preprocessor for a document search system.
The system searches a library of medical device documents (FDA clearances, clinical evidence, product brochures, research articles) for Integra LifeSciences.

Given the user's query, return a JSON object with:
- "semantic_query": a rephrased version of the query optimized for matching against short document summaries (~200 words). Expand abbreviations, add synonyms, clarify intent.
- "keyword_terms": a list of specific strings that should be searched as exact text in the full document body. Include identifiers, codes, part numbers, citation references, product names, author names, dates, or any term where an exact substring match would help. Return an empty list if the query is purely conceptual/topical.
- "reasoning": one sentence explaining how you interpreted the query.

Examples:
- Query: "45:28-33" → {"semantic_query": "research article published in journal volume 45 pages 28 to 33", "keyword_terms": ["45:28-33", "45:28"], "reasoning": "User provided a journal citation in volume:pages format."}
- Query: "Bactiseal catheter" → {"semantic_query": "antimicrobial catheter with Bactiseal technology for hydrocephalus", "keyword_terms": ["Bactiseal"], "reasoning": "Bactiseal is a specific product name worth exact-matching."}
- Query: "wound healing brochure" → {"semantic_query": "wound healing product brochure collagen dermal regeneration", "keyword_terms": [], "reasoning": "Purely topical query, no specific identifiers to exact-match."}

Return ONLY the JSON object, no other text."""


def _get_openai_client() -> OpenAI:
    cfg = Config()
    token = cfg.authenticate()["Authorization"].replace("Bearer ", "")
    return OpenAI(
        api_key=token,
        base_url=f"{cfg.host}/serving-endpoints",
    )


def _classify_query(client: OpenAI, message: str) -> dict:
    """Use Gemini to classify the query and extract search terms."""
    try:
        response = client.chat.completions.create(
            model=CLASSIFIER_MODEL,
            messages=[
                {"role": "system", "content": CLASSIFIER_PROMPT},
                {"role": "user", "content": message},
            ],
            max_tokens=256,
        )
        raw = response.choices[0].message.content or "{}"
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(raw)
    except (json.JSONDecodeError, Exception):
        # Fallback: use original query, no keyword search
        return {
            "semantic_query": message,
            "keyword_terms": [],
            "reasoning": "Classifier unavailable, using original query.",
        }


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

    # Step 1: Gemini classifies the query
    classification = _classify_query(client, message)
    semantic_query = classification.get("semantic_query", message)
    keyword_terms = classification.get("keyword_terms", [])
    reasoning = classification.get("reasoning", "")

    # Step 2: Run searches
    semantic_results = search_documents(semantic_query)
    keyword_results = search_by_keyword(keyword_terms)

    # Step 3: Merge and deduplicate
    all_results = _deduplicate_results(keyword_results + semantic_results)

    # Step 4: Build search context for Claude
    search_sections = []
    if reasoning:
        search_sections.append(f"Query analysis: {reasoning}")
    if keyword_results:
        search_sections.append(
            f"Keyword matches (exact text match for: {', '.join(keyword_terms)}):\n"
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
