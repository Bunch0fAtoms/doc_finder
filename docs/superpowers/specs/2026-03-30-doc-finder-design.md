# Doc Finder — Design Spec

## Overview

Internal document search app for Integra LifeSciences regulatory/clinical teams. Users describe the document they need via a chat interface, an AI agent searches the corpus using semantic search, and the best matching document is displayed in a side panel.

Deployed as a Databricks App on workspace `fevm-morgan-stable-classic-6df0yw`.

## Workspace Resources

- **Catalog**: `morgan_stable_classic_6df0yw_catalog`
- **Schema**: `doc_finder`
- **Volume**: `raw_docs` — contains source PDFs (currently 4, expected to scale to 1M)
- **Workspace URL**: `https://fevm-morgan-stable-classic-6df0yw.cloud.databricks.com/`

## Data Pipeline

Three scripts run sequentially to prepare the search index. Re-run when new PDFs are added.

### Step 1: Parse PDFs (`pipeline/01_parse_docs.py`)

- Use `ai_parse_document` to extract text from each PDF in the volume
- Output table: `doc_finder.parsed_docs` (columns: `filename`, `full_text`)
- Concatenates all pages per document into a single text field

### Step 2: Summarize Documents (`pipeline/02_summarize_docs.py`)

- Use `ai_query()` with a foundation model to generate a ~200-word summary per document
- Summary captures: title, document type, key topics, products/devices, regulatory info
- Output table: `doc_finder.doc_summaries` (columns: `filename`, `summary`, `full_text`)
- One row per document — designed to scale to 1M documents

### Step 3: Create Vector Search Index (`pipeline/03_create_vs_index.py`)

- Create a Vector Search endpoint (if not exists)
- Create a Delta Sync index on `doc_finder.doc_summaries` with embeddings on the `summary` column
- Embedding model: `databricks-gte-large-en` (auto-computed by the index)
- One embedding per document (not per chunk)

## Agent Design

### Model

`databricks-claude-sonnet-4-6` via Foundation Model API

### Tool

Single tool: `search_documents`
- Input: search query string
- Action: queries Vector Search index over document summaries
- Output: top-5 results with filename, summary, and similarity score

### Agent Flow

1. Receive user message + full conversation history
2. Refine user intent into a search query (e.g., "wound healing thing" -> "clinical evidence wound healing diabetic foot ulcer")
3. Call `search_documents` tool
4. Pick best matching document by aggregating relevance
5. Return natural language explanation of why it matched + structured metadata `{filename, score}`
6. Frontend uses metadata to load the PDF in the viewer

### Conversation Memory

- Conversation history maintained in React frontend state (message list)
- Full history passed to agent on each call
- No persistent storage — session-scoped only
- Supports conversational refinement ("no, the other one")

## App Architecture

### Frontend (React)

- **Left panel**: Chat interface — message input, scrollable conversation history
- **Right panel**: PDF viewer — loads matched document when agent returns a result
- PDF fetched from backend endpoint

### Backend (FastAPI)

- `POST /chat` — accepts `{message, history}`, calls agent, returns `{response, filename, score}`
- `GET /docs/{filename}` — serves PDF file from the volume
- OAuth via Databricks Apps for authentication

### Databricks App Resources

- SQL warehouse (for `ai_parse_document`, `ai_query`)
- Vector Search endpoint
- Volume access (serving PDFs)

## Project Structure

```
doc_finder/
├── raw_docs/                    # PDFs (already exists, in volume)
├── .gitignore
├── app.yaml                     # Databricks App config
├── requirements.txt
├── backend/
│   ├── main.py                  # FastAPI app
│   ├── agent.py                 # Agent logic (Foundation Model API + tool)
│   └── vector_search.py         # Vector Search client
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx              # Main layout (chat + PDF panels)
│   │   ├── components/
│   │   │   ├── ChatPanel.tsx    # Chat UI
│   │   │   └── PdfViewer.tsx    # PDF viewer panel
│   │   └── index.tsx
│   └── public/
│       └── index.html
└── pipeline/
    ├── 01_parse_docs.py         # Parse PDFs with ai_parse_document
    ├── 02_summarize_docs.py     # Generate summaries with ai_query
    └── 03_create_vs_index.py    # Create Vector Search endpoint + index
```

## Data Flow

```
User types message
  -> React sends POST /chat (message + history)
  -> FastAPI calls Foundation Model API (databricks-claude-sonnet-4-6)
  -> Agent calls search_documents tool -> Vector Search query
  -> Agent returns explanation + {filename, score}
  -> React renders response in chat + loads PDF in right panel
  -> PDF fetched via GET /docs/{filename} from volume
```

## Future Work

- Wrap in Databricks Asset Bundles (DABs) for deployment management
- Automated pipeline trigger when new PDFs are uploaded to the volume
- Scale testing at 1M documents
- MLflow experiment tracking: log user inputs and agent responses, with LLM judges evaluating response quality (relevance, correctness, groundedness)
- Cost dashboard: AI/BI (Lakeview) dashboard reporting DBU and $DBU consumed by the data pipeline jobs and the app's serving/warehouse usage
