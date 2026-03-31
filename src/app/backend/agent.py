# backend/agent.py
"""
Chat agent using Foundation Model API (databricks-claude-sonnet-4-6).
Uses a single-call pattern: search first, then pass results to the model.
"""
import json
import os
from openai import OpenAI
from databricks.sdk.core import Config
from backend.vector_search import search_documents

MODEL = os.getenv("FOUNDATION_MODEL", "databricks-claude-sonnet-4-6")

SYSTEM_PROMPT = """You are a document finder assistant for Integra LifeSciences.
Your job is to help employees find the right document from the company's document library.

You will receive search results from the document library along with the user's query.
Based on the results:
1. Recommend the best matching document
2. Explain briefly why it matches their request
3. Include the exact filename in your response

If the user asks to refine or says "not that one", look at the search results for alternatives.

IMPORTANT: Always include a JSON block at the end of your response in this exact format:
```json
{"filename": "the_matched_file.pdf", "score": 0.85}
```
If no good match was found, set filename to null."""


def _get_openai_client() -> OpenAI:
    cfg = Config()
    token = cfg.authenticate()["Authorization"].replace("Bearer ", "")
    return OpenAI(
        api_key=token,
        base_url=f"{cfg.host}/serving-endpoints",
    )


def chat(message: str, history: list[dict]) -> dict:
    """
    Process a chat message and return the agent's response.

    Searches first, then passes results to the model in a single call.
    """
    client = _get_openai_client()

    # Search documents based on the user's message
    search_results = search_documents(message)
    search_context = json.dumps(search_results, indent=2)

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
