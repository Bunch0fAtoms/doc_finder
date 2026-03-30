# backend/agent.py
"""
Chat agent using Foundation Model API (databricks-claude-sonnet-4-6) with
a search_documents tool for finding relevant documents.
"""
import json
import os
from openai import OpenAI
from databricks.sdk.core import Config
from backend.vector_search import search_documents

MODEL = os.getenv("FOUNDATION_MODEL", "databricks-claude-sonnet-4-6")

SYSTEM_PROMPT = """You are a document finder assistant for Integra LifeSciences.
Your job is to help employees find the right document from the company's document library.

When a user describes what they're looking for, use the search_documents tool to find matching documents.
Always call the tool before answering — do not guess which document to recommend.

After receiving search results:
1. Recommend the best matching document
2. Explain briefly why it matches their request
3. Include the exact filename in your response

If the user asks to refine or says "not that one", search again with adjusted terms.

IMPORTANT: Always include a JSON block at the end of your response in this exact format:
```json
{"filename": "the_matched_file.pdf", "score": 0.85}
```
If no good match was found, set filename to null."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Search the document library by semantic similarity. Use this to find documents matching the user's description.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query describing the document to find",
                    }
                },
                "required": ["query"],
            },
        },
    }
]


def _get_openai_client() -> OpenAI:
    cfg = Config()
    token = cfg.authenticate()["Authorization"].replace("Bearer ", "")
    return OpenAI(
        api_key=token,
        base_url=f"{cfg.host}/serving-endpoints",
    )


def _handle_tool_calls(tool_calls) -> list[dict]:
    """Execute tool calls and return results."""
    results = []
    for tc in tool_calls:
        if tc.function.name == "search_documents":
            args = json.loads(tc.function.arguments)
            search_results = search_documents(args["query"])
            results.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(search_results),
            })
    return results


def chat(message: str, history: list[dict]) -> dict:
    """
    Process a chat message and return the agent's response.

    Args:
        message: The user's message
        history: List of prior messages [{"role": "user"|"assistant", "content": "..."}]

    Returns:
        {"response": str, "filename": str|None, "score": float|None}
    """
    client = _get_openai_client()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        max_tokens=1024,
    )

    msg = response.choices[0].message

    # Handle tool calls in a loop
    while msg.tool_calls:
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        })
        tool_results = _handle_tool_calls(msg.tool_calls)
        messages.extend(tool_results)

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=1024,
        )
        msg = response.choices[0].message

    content = msg.content or ""

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
