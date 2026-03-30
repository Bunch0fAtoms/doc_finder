# Doc Finder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Databricks App that lets Integra LifeSciences employees find relevant documents by chatting with an AI agent, with the best matching PDF displayed in a side panel.

**Architecture:** Data pipeline parses PDFs from a Unity Catalog volume, generates per-document summaries, and indexes them in Vector Search. A FastAPI backend exposes a chat endpoint that calls the Foundation Model API (databricks-claude-sonnet-4-6) with a search tool. A React frontend provides a split-pane chat + PDF viewer.

**Tech Stack:** Python (FastAPI, databricks-sdk, databricks-vectorsearch, openai), React + TypeScript, Databricks Vector Search, Foundation Model API, Unity Catalog Volumes

---

## File Structure

```
doc_finder/
├── app.yaml                     # Databricks App config
├── requirements.txt             # Python dependencies
├── backend/
│   ├── main.py                  # FastAPI app — routes, static file serving
│   ├── agent.py                 # Agent logic — Foundation Model API + tool loop
│   └── vector_search.py         # Vector Search query client
├── frontend/
│   ├── package.json             # React dependencies
│   ├── tsconfig.json            # TypeScript config
│   ├── vite.config.ts           # Vite build config (proxy + output to ../static)
│   ├── index.html               # HTML entry point
│   └── src/
│       ├── main.tsx             # React entry point
│       ├── App.tsx              # Main layout — split pane
│       ├── App.css              # Styles
│       └── components/
│           ├── ChatPanel.tsx    # Chat UI — input, messages, scroll
│           └── PdfViewer.tsx    # PDF viewer — iframe embed
└── pipeline/
    ├── 01_parse_docs.py         # Parse PDFs with ai_parse_document via SQL
    ├── 02_summarize_docs.py     # Summarize with ai_query via SQL
    └── 03_create_vs_index.py    # Create Vector Search endpoint + index
```

## Environment Constants

Used throughout the plan — reference these values:

| Constant | Value |
|----------|-------|
| Workspace URL | `https://fevm-morgan-stable-classic-6df0yw.cloud.databricks.com` |
| CLI Profile | `fe-vm-morgan-stable-classic-6df0yw` |
| Catalog | `morgan_stable_classic_6df0yw_catalog` |
| Schema | `doc_finder` |
| Volume | `raw_docs` |
| Volume Path | `/Volumes/morgan_stable_classic_6df0yw_catalog/doc_finder/raw_docs` |
| Warehouse ID | `718f1b203cdea5c4` |
| VS Endpoint Name | `doc_finder_vs_endpoint` |
| VS Index Name | `morgan_stable_classic_6df0yw_catalog.doc_finder.doc_summaries_index` |
| Foundation Model | `databricks-claude-sonnet-4-6` |
| Embedding Model | `databricks-gte-large-en` |

---

### Task 1: Data Pipeline — Parse PDFs

**Files:**
- Create: `pipeline/01_parse_docs.py`

This script runs on a Databricks SQL warehouse via the CLI. It uses `ai_parse_document` to extract text from each PDF in the volume and writes results to a Delta table.

- [ ] **Step 1: Create the parse script**

```python
# pipeline/01_parse_docs.py
"""
Parse PDFs from Unity Catalog volume using ai_parse_document.
Run via: databricks sql query --profile=fe-vm-morgan-stable-classic-6df0yw
Or execute the SQL directly on a warehouse.
"""
import os
import sys
from databricks import sql
from databricks.sdk.core import Config

CATALOG = "morgan_stable_classic_6df0yw_catalog"
SCHEMA = "doc_finder"
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/raw_docs"
WAREHOUSE_ID = "718f1b203cdea5c4"

def get_connection():
    cfg = Config(
        host="https://fevm-morgan-stable-classic-6df0yw.cloud.databricks.com",
        profile="fe-vm-morgan-stable-classic-6df0yw",
    )
    return sql.connect(
        server_hostname=cfg.host.replace("https://", ""),
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: cfg.authenticate,
    )

def run():
    conn = get_connection()
    cursor = conn.cursor()

    print("Creating parsed_docs table...")
    cursor.execute(f"""
        CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.parsed_docs AS
        SELECT
            regexp_extract(path, '[^/]+$') AS filename,
            ai_parse_document(content, map('version', '2.0'))['parsed_document'] AS parsed_text
        FROM READ_FILES('{VOLUME_PATH}/', format => 'binaryFile')
    """)

    cursor.execute(f"SELECT filename FROM {CATALOG}.{SCHEMA}.parsed_docs")
    rows = cursor.fetchall()
    print(f"Parsed {len(rows)} documents:")
    for row in rows:
        print(f"  - {row[0]}")

    cursor.close()
    conn.close()

if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Run the parse script**

```bash
cd /Users/morgan.williams/Vibe/Integra/doc_finder
pip install databricks-sql-connector databricks-sdk
python pipeline/01_parse_docs.py
```

Expected: Output showing 4 parsed documents.

- [ ] **Step 3: Verify the parsed_docs table**

```bash
databricks api post /api/2.1/sql/statements \
  --profile=fe-vm-morgan-stable-classic-6df0yw \
  --json '{
    "warehouse_id": "718f1b203cdea5c4",
    "statement": "SELECT filename, length(parsed_text) as text_len FROM morgan_stable_classic_6df0yw_catalog.doc_finder.parsed_docs"
  }'
```

Expected: 4 rows with filenames and text lengths > 0.

- [ ] **Step 4: Commit**

```bash
git add pipeline/01_parse_docs.py
git commit -m "feat: add PDF parsing pipeline script"
```

---

### Task 2: Data Pipeline — Summarize Documents

**Files:**
- Create: `pipeline/02_summarize_docs.py`

Uses `ai_query()` to generate a ~200-word summary per document for embedding.

- [ ] **Step 1: Create the summarize script**

```python
# pipeline/02_summarize_docs.py
"""
Generate document summaries using ai_query for vector search indexing.
"""
from databricks import sql
from databricks.sdk.core import Config

CATALOG = "morgan_stable_classic_6df0yw_catalog"
SCHEMA = "doc_finder"
WAREHOUSE_ID = "718f1b203cdea5c4"

def get_connection():
    cfg = Config(
        host="https://fevm-morgan-stable-classic-6df0yw.cloud.databricks.com",
        profile="fe-vm-morgan-stable-classic-6df0yw",
    )
    return sql.connect(
        server_hostname=cfg.host.replace("https://", ""),
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: cfg.authenticate,
    )

SUMMARY_PROMPT = """Summarize this document in under 200 words. Include:
- Document title or subject
- Document type (FDA clearance, research article, product brochure, clinical evidence, etc.)
- Key topics and findings
- Products, devices, or technologies mentioned
- Regulatory information if applicable

Document text:
"""

def run():
    conn = get_connection()
    cursor = conn.cursor()

    print("Creating doc_summaries table...")
    cursor.execute(f"""
        CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.doc_summaries (
            filename STRING,
            summary STRING,
            full_text STRING
        )
        USING DELTA
        TBLPROPERTIES (delta.enableChangeDataFeed = true)
    """)

    cursor.execute(f"""
        INSERT INTO {CATALOG}.{SCHEMA}.doc_summaries
        SELECT
            filename,
            ai_query(
                'databricks-meta-llama-3-3-70b-instruct',
                CONCAT('{SUMMARY_PROMPT}', LEFT(parsed_text, 8000))
            ) AS summary,
            parsed_text AS full_text
        FROM {CATALOG}.{SCHEMA}.parsed_docs
    """)

    cursor.execute(f"SELECT filename, summary FROM {CATALOG}.{SCHEMA}.doc_summaries")
    rows = cursor.fetchall()
    print(f"Summarized {len(rows)} documents:")
    for row in rows:
        print(f"\n--- {row[0]} ---")
        print(row[1][:200] + "...")

    cursor.close()
    conn.close()

if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Run the summarize script**

```bash
python pipeline/02_summarize_docs.py
```

Expected: Output showing 4 documents with summaries.

- [ ] **Step 3: Verify the doc_summaries table**

Confirm Change Data Feed is enabled (required for Delta Sync index):

```bash
databricks api post /api/2.1/sql/statements \
  --profile=fe-vm-morgan-stable-classic-6df0yw \
  --json '{
    "warehouse_id": "718f1b203cdea5c4",
    "statement": "SELECT filename, length(summary) as summary_len FROM morgan_stable_classic_6df0yw_catalog.doc_finder.doc_summaries"
  }'
```

Expected: 4 rows with summary lengths > 0.

- [ ] **Step 4: Commit**

```bash
git add pipeline/02_summarize_docs.py
git commit -m "feat: add document summarization pipeline script"
```

---

### Task 3: Data Pipeline — Create Vector Search Index

**Files:**
- Create: `pipeline/03_create_vs_index.py`

Creates a Vector Search endpoint and a Delta Sync index with auto-computed embeddings on the summary column.

- [ ] **Step 1: Create the vector search setup script**

```python
# pipeline/03_create_vs_index.py
"""
Create Vector Search endpoint and Delta Sync index for document summaries.
"""
from databricks.vector_search.client import VectorSearchClient
from databricks.sdk.core import Config
import time

CATALOG = "morgan_stable_classic_6df0yw_catalog"
SCHEMA = "doc_finder"
VS_ENDPOINT_NAME = "doc_finder_vs_endpoint"
VS_INDEX_NAME = f"{CATALOG}.{SCHEMA}.doc_summaries_index"
SOURCE_TABLE = f"{CATALOG}.{SCHEMA}.doc_summaries"
EMBEDDING_MODEL = "databricks-gte-large-en"

def run():
    cfg = Config(
        host="https://fevm-morgan-stable-classic-6df0yw.cloud.databricks.com",
        profile="fe-vm-morgan-stable-classic-6df0yw",
    )
    client = VectorSearchClient(
        workspace_url=cfg.host,
        personal_access_token=cfg.authenticate()["Authorization"].replace("Bearer ", ""),
    )

    # Create endpoint if it doesn't exist
    try:
        client.get_endpoint(VS_ENDPOINT_NAME)
        print(f"Endpoint '{VS_ENDPOINT_NAME}' already exists.")
    except Exception:
        print(f"Creating endpoint '{VS_ENDPOINT_NAME}'...")
        client.create_endpoint_and_wait(
            name=VS_ENDPOINT_NAME,
            endpoint_type="STANDARD",
        )
        print("Endpoint created.")

    # Create Delta Sync index
    try:
        client.get_index(
            endpoint_name=VS_ENDPOINT_NAME,
            index_name=VS_INDEX_NAME,
        )
        print(f"Index '{VS_INDEX_NAME}' already exists.")
    except Exception:
        print(f"Creating index '{VS_INDEX_NAME}'...")
        client.create_delta_sync_index_and_wait(
            endpoint_name=VS_ENDPOINT_NAME,
            index_name=VS_INDEX_NAME,
            source_table_name=SOURCE_TABLE,
            primary_key="filename",
            embedding_source_column="summary",
            embedding_model_endpoint_name=EMBEDDING_MODEL,
            pipeline_type="TRIGGERED",
        )
        print("Index created and synced.")

    # Verify by querying
    index = client.get_index(
        endpoint_name=VS_ENDPOINT_NAME,
        index_name=VS_INDEX_NAME,
    )
    results = index.similarity_search(
        query_text="FDA medical device clearance",
        columns=["filename", "summary"],
        num_results=3,
    )
    print("\nTest query: 'FDA medical device clearance'")
    for doc in results.get("result", {}).get("data_array", []):
        print(f"  - {doc[0]} (score: {doc[-1]:.3f})")

if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Run the vector search setup script**

```bash
pip install databricks-vectorsearch
python pipeline/03_create_vs_index.py
```

Expected: Endpoint created (or exists), index created and synced, test query returns K243531.pdf as top result.

Note: Endpoint creation can take 5-10 minutes. Index sync takes 2-5 minutes after that.

- [ ] **Step 3: Commit**

```bash
git add pipeline/03_create_vs_index.py
git commit -m "feat: add vector search index creation script"
```

---

### Task 4: Backend — Vector Search Client

**Files:**
- Create: `backend/__init__.py`
- Create: `backend/vector_search.py`

Encapsulates Vector Search queries for use by the agent.

- [ ] **Step 1: Create the vector search client module**

```python
# backend/__init__.py
```

```python
# backend/vector_search.py
"""
Vector Search client for querying document summaries.
"""
import os
from databricks.vector_search.client import VectorSearchClient
from databricks.sdk.core import Config


VS_ENDPOINT_NAME = os.getenv("VS_ENDPOINT_NAME", "doc_finder_vs_endpoint")
VS_INDEX_NAME = os.getenv(
    "VS_INDEX_NAME",
    "morgan_stable_classic_6df0yw_catalog.doc_finder.doc_summaries_index",
)


def _get_client():
    cfg = Config()
    token = cfg.authenticate()["Authorization"].replace("Bearer ", "")
    return VectorSearchClient(
        workspace_url=cfg.host,
        personal_access_token=token,
    )


def search_documents(query: str, num_results: int = 5) -> list[dict]:
    """
    Search document summaries by semantic similarity.

    Returns list of dicts with keys: filename, summary, score
    """
    client = _get_client()
    index = client.get_index(
        endpoint_name=VS_ENDPOINT_NAME,
        index_name=VS_INDEX_NAME,
    )
    results = index.similarity_search(
        query_text=query,
        columns=["filename", "summary"],
        num_results=num_results,
    )
    data = results.get("result", {}).get("data_array", [])
    return [
        {"filename": row[0], "summary": row[1], "score": row[2]}
        for row in data
    ]
```

- [ ] **Step 2: Test locally**

```bash
cd /Users/morgan.williams/Vibe/Integra/doc_finder
DATABRICKS_HOST=https://fevm-morgan-stable-classic-6df0yw.cloud.databricks.com \
DATABRICKS_CONFIG_PROFILE=fe-vm-morgan-stable-classic-6df0yw \
python -c "
from backend.vector_search import search_documents
results = search_documents('FDA device clearance')
for r in results:
    print(f\"{r['filename']}: {r['score']:.3f}\")
"
```

Expected: Returns ranked documents with K243531.pdf scoring highest.

- [ ] **Step 3: Commit**

```bash
git add backend/
git commit -m "feat: add vector search client module"
```

---

### Task 5: Backend — Agent Logic

**Files:**
- Create: `backend/agent.py`

Implements the chat agent using Foundation Model API with tool calling.

- [ ] **Step 1: Create the agent module**

```python
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
```

- [ ] **Step 2: Test the agent locally**

```bash
cd /Users/morgan.williams/Vibe/Integra/doc_finder
DATABRICKS_HOST=https://fevm-morgan-stable-classic-6df0yw.cloud.databricks.com \
DATABRICKS_CONFIG_PROFILE=fe-vm-morgan-stable-classic-6df0yw \
python -c "
from backend.agent import chat
result = chat('Find me the FDA clearance document for a shunt catheter', [])
print('Response:', result['response'][:300])
print('Filename:', result['filename'])
print('Score:', result['score'])
"
```

Expected: Returns response mentioning K243531.pdf with explanation.

- [ ] **Step 3: Commit**

```bash
git add backend/agent.py
git commit -m "feat: add chat agent with Foundation Model API and tool calling"
```

---

### Task 6: Backend — FastAPI App

**Files:**
- Create: `backend/main.py`
- Create: `requirements.txt`

FastAPI app with chat endpoint and PDF serving.

- [ ] **Step 1: Create the FastAPI main module**

```python
# backend/main.py
"""
FastAPI application for Doc Finder.
Serves the chat API and PDF files from Unity Catalog volumes.
"""
import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from databricks.sdk import WorkspaceClient
from backend.agent import chat as agent_chat

app = FastAPI(title="Doc Finder")

CATALOG = os.getenv("CATALOG", "morgan_stable_classic_6df0yw_catalog")
SCHEMA = os.getenv("SCHEMA", "doc_finder")
VOLUME = os.getenv("VOLUME", "raw_docs")
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


class ChatResponse(BaseModel):
    response: str
    filename: str | None = None
    score: float | None = None


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """Process a chat message through the document finder agent."""
    try:
        result = agent_chat(req.message, req.history)
        return ChatResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/docs/{filename}")
async def get_document(filename: str):
    """Serve a PDF from the Unity Catalog volume."""
    try:
        w = WorkspaceClient()
        file_path = f"{VOLUME_PATH}/{filename}"
        resp = w.files.download(file_path)
        content = resp.read()
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Document not found: {filename}")


# Serve React static files (built frontend)
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
```

- [ ] **Step 2: Create requirements.txt**

```
fastapi>=0.115.0
uvicorn>=0.24.0
databricks-sdk>=0.38.0
databricks-sql-connector>=3.0.0
databricks-vectorsearch>=0.40
openai>=1.0.0
pydantic>=2.0.0
```

- [ ] **Step 3: Commit**

```bash
git add backend/main.py requirements.txt
git commit -m "feat: add FastAPI app with chat and PDF serving endpoints"
```

---

### Task 7: Frontend — React App Scaffold

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "doc-finder-frontend",
  "private": true,
  "version": "1.0.0",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.4",
    "typescript": "^5.6.3",
    "vite": "^6.0.3"
  }
}
```

- [ ] **Step 2: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true
  },
  "include": ["src"]
}
```

- [ ] **Step 3: Create vite.config.ts**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
```

- [ ] **Step 4: Create index.html**

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Doc Finder</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Create main.tsx**

```tsx
// frontend/src/main.tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./App.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

- [ ] **Step 6: Install dependencies and verify build**

```bash
cd /Users/morgan.williams/Vibe/Integra/doc_finder/frontend
npm install
npm run build
```

Expected: Build succeeds, `static/` directory created with index.html and JS bundles.

- [ ] **Step 7: Commit**

```bash
cd /Users/morgan.williams/Vibe/Integra/doc_finder
git add frontend/package.json frontend/tsconfig.json frontend/vite.config.ts frontend/index.html frontend/src/main.tsx
git commit -m "feat: scaffold React frontend with Vite"
```

---

### Task 8: Frontend — Chat Panel Component

**Files:**
- Create: `frontend/src/components/ChatPanel.tsx`

- [ ] **Step 1: Create ChatPanel component**

```tsx
// frontend/src/components/ChatPanel.tsx
import React, { useState, useRef, useEffect } from "react";

interface Message {
  role: "user" | "assistant";
  content: string;
  filename?: string | null;
  score?: number | null;
}

interface ChatPanelProps {
  messages: Message[];
  onSendMessage: (message: string) => void;
  isLoading: boolean;
}

export default function ChatPanel({
  messages,
  onSendMessage,
  isLoading,
}: ChatPanelProps) {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;
    onSendMessage(input.trim());
    setInput("");
  };

  const stripJsonBlock = (text: string): string => {
    return text.replace(/```json[\s\S]*?```/g, "").trim();
  };

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <h2>Doc Finder</h2>
        <p>Describe the document you're looking for</p>
      </div>
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p>Try asking:</p>
            <ul>
              <li>"Find the FDA 510(k) clearance for the shunt catheter"</li>
              <li>"Show me clinical evidence for diabetic foot ulcers"</li>
              <li>"I need the collagen technology brochure"</li>
            </ul>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`chat-message ${msg.role}`}>
            <div className="message-content">
              {msg.role === "assistant"
                ? stripJsonBlock(msg.content)
                : msg.content}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="chat-message assistant">
            <div className="message-content loading">Searching documents...</div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <form className="chat-input" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Describe the document you need..."
          disabled={isLoading}
        />
        <button type="submit" disabled={isLoading || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx
git commit -m "feat: add ChatPanel component"
```

---

### Task 9: Frontend — PDF Viewer Component

**Files:**
- Create: `frontend/src/components/PdfViewer.tsx`

- [ ] **Step 1: Create PdfViewer component**

```tsx
// frontend/src/components/PdfViewer.tsx

interface PdfViewerProps {
  filename: string | null;
}

export default function PdfViewer({ filename }: PdfViewerProps) {
  if (!filename) {
    return (
      <div className="pdf-viewer empty">
        <div className="pdf-placeholder">
          <p>No document selected</p>
          <p>Chat with the assistant to find a document</p>
        </div>
      </div>
    );
  }

  return (
    <div className="pdf-viewer">
      <div className="pdf-header">
        <span className="pdf-filename">{filename}</span>
        <a
          href={`/api/docs/${encodeURIComponent(filename)}`}
          target="_blank"
          rel="noopener noreferrer"
          className="pdf-download"
        >
          Open in new tab
        </a>
      </div>
      <iframe
        src={`/api/docs/${encodeURIComponent(filename)}`}
        title={filename}
        className="pdf-frame"
      />
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/PdfViewer.tsx
git commit -m "feat: add PdfViewer component"
```

---

### Task 10: Frontend — App Layout and Styles

**Files:**
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/App.css`

Wires together the chat panel and PDF viewer in a split layout.

- [ ] **Step 1: Create App.tsx**

```tsx
// frontend/src/App.tsx
import { useState } from "react";
import ChatPanel from "./components/ChatPanel";
import PdfViewer from "./components/PdfViewer";

interface Message {
  role: "user" | "assistant";
  content: string;
  filename?: string | null;
  score?: number | null;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [currentDoc, setCurrentDoc] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSendMessage = async (message: string) => {
    const userMsg: Message = { role: "user", content: message };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setIsLoading(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          history: updatedMessages.map((m) => ({
            role: m.role,
            content: m.content,
          })),
        }),
      });

      if (!response.ok) throw new Error("Chat request failed");

      const data = await response.json();
      const assistantMsg: Message = {
        role: "assistant",
        content: data.response,
        filename: data.filename,
        score: data.score,
      };

      setMessages([...updatedMessages, assistantMsg]);

      if (data.filename) {
        setCurrentDoc(data.filename);
      }
    } catch (error) {
      setMessages([
        ...updatedMessages,
        {
          role: "assistant",
          content: "Sorry, something went wrong. Please try again.",
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="app">
      <ChatPanel
        messages={messages}
        onSendMessage={handleSendMessage}
        isLoading={isLoading}
      />
      <PdfViewer filename={currentDoc} />
    </div>
  );
}
```

- [ ] **Step 2: Create App.css**

```css
/* frontend/src/App.css */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #f5f5f5;
}

.app {
  display: flex;
  height: 100vh;
  width: 100vw;
}

/* Chat Panel */
.chat-panel {
  width: 400px;
  min-width: 350px;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-right: 1px solid #e0e0e0;
}

.chat-header {
  padding: 16px 20px;
  border-bottom: 1px solid #e0e0e0;
  background: #1b3a4b;
  color: #fff;
}

.chat-header h2 {
  font-size: 18px;
  margin-bottom: 4px;
}

.chat-header p {
  font-size: 13px;
  opacity: 0.8;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.chat-empty {
  color: #888;
  padding: 20px 0;
}

.chat-empty ul {
  margin-top: 8px;
  padding-left: 20px;
}

.chat-empty li {
  margin: 6px 0;
  font-size: 14px;
  font-style: italic;
}

.chat-message {
  margin-bottom: 12px;
}

.chat-message .message-content {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.5;
  max-width: 90%;
  white-space: pre-wrap;
}

.chat-message.user .message-content {
  background: #1b3a4b;
  color: #fff;
  margin-left: auto;
  border-bottom-right-radius: 4px;
}

.chat-message.assistant .message-content {
  background: #f0f0f0;
  color: #333;
  border-bottom-left-radius: 4px;
}

.chat-message .loading {
  color: #888;
  font-style: italic;
}

.chat-input {
  display: flex;
  padding: 12px 16px;
  border-top: 1px solid #e0e0e0;
  gap: 8px;
}

.chat-input input {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
}

.chat-input input:focus {
  border-color: #1b3a4b;
}

.chat-input button {
  padding: 10px 20px;
  background: #1b3a4b;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
}

.chat-input button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* PDF Viewer */
.pdf-viewer {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #fafafa;
}

.pdf-viewer.empty {
  align-items: center;
  justify-content: center;
}

.pdf-placeholder {
  text-align: center;
  color: #999;
}

.pdf-placeholder p:first-child {
  font-size: 18px;
  margin-bottom: 8px;
}

.pdf-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: #fff;
  border-bottom: 1px solid #e0e0e0;
}

.pdf-filename {
  font-weight: 600;
  font-size: 14px;
}

.pdf-download {
  font-size: 13px;
  color: #1b3a4b;
}

.pdf-frame {
  flex: 1;
  border: none;
  width: 100%;
}
```

- [ ] **Step 3: Build the frontend**

```bash
cd /Users/morgan.williams/Vibe/Integra/doc_finder/frontend
npm run build
```

Expected: `static/` directory created at `doc_finder/static/`.

- [ ] **Step 4: Commit**

```bash
cd /Users/morgan.williams/Vibe/Integra/doc_finder
git add frontend/src/App.tsx frontend/src/App.css static/
git commit -m "feat: add app layout with chat + PDF viewer split pane"
```

---

### Task 11: Databricks App Configuration and Deployment

**Files:**
- Create: `app.yaml`
- Update: `.gitignore`

- [ ] **Step 1: Create app.yaml**

```yaml
command:
  - uvicorn
  - backend.main:app
  - --host
  - "0.0.0.0"
  - --port
  - "8000"

env:
  - name: DATABRICKS_WAREHOUSE_ID
    valueFrom: sql-warehouse

  - name: VS_ENDPOINT_NAME
    value: doc_finder_vs_endpoint

  - name: VS_INDEX_NAME
    value: morgan_stable_classic_6df0yw_catalog.doc_finder.doc_summaries_index

  - name: CATALOG
    value: morgan_stable_classic_6df0yw_catalog

  - name: SCHEMA
    value: doc_finder

  - name: VOLUME
    value: raw_docs

  - name: FOUNDATION_MODEL
    value: databricks-claude-sonnet-4-6
```

- [ ] **Step 2: Update .gitignore**

```
.DS_Store
node_modules/
static/
__pycache__/
*.pyc
.env
```

- [ ] **Step 3: Deploy the app**

```bash
cd /Users/morgan.williams/Vibe/Integra/doc_finder
databricks apps create doc-finder \
  --profile=fe-vm-morgan-stable-classic-6df0yw

databricks apps deploy doc-finder \
  --source-code-path . \
  --profile=fe-vm-morgan-stable-classic-6df0yw
```

After deploying, add resources via the Databricks Apps UI:
1. Navigate to the app in the workspace
2. Add resource: SQL Warehouse → select `Serverless Starter Warehouse` → key: `sql-warehouse`
3. Add resource: Vector Search Index → select `doc_summaries_index` → key: `vector-search-index`

- [ ] **Step 4: Verify the deployment**

```bash
databricks apps get doc-finder --profile=fe-vm-morgan-stable-classic-6df0yw
```

Expected: App status shows RUNNING. Open the app URL in browser to test.

- [ ] **Step 5: Commit**

```bash
git add app.yaml .gitignore
git commit -m "feat: add Databricks App config and deploy"
```

---

### Task 12: End-to-End Test

- [ ] **Step 1: Open the app in browser**

Get the app URL:
```bash
databricks apps get doc-finder --profile=fe-vm-morgan-stable-classic-6df0yw --output=json | python3 -c "import sys,json; print(json.load(sys.stdin).get('url',''))"
```

Open the URL in your browser.

- [ ] **Step 2: Test document search**

In the chat panel, send: "Find me the FDA clearance for the shunt catheter"

Expected:
- Agent responds mentioning K243531.pdf with explanation
- PDF viewer loads K243531.pdf on the right panel

- [ ] **Step 3: Test conversational refinement**

Send: "No, show me the wound healing document instead"

Expected:
- Agent responds mentioning 1579123072.pdf (Omnigraft clinical evidence)
- PDF viewer switches to the new document

- [ ] **Step 4: Test remaining documents**

Send: "I need the Integra tissue technologies brochure"

Expected:
- Agent responds with 1595515568.pdf
- PDF viewer loads the collagen technology brochure

- [ ] **Step 5: Push to git**

```bash
git push origin main
```
