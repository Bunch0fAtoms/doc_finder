# Doc Finder

Internal document search app for Integra LifeSciences. Employees describe the document they need via a chat interface, an AI agent searches the corpus using semantic search, and the best matching PDF is displayed in a side panel.

## Architecture

- **Frontend**: React (CDN-loaded, single HTML file) with split-pane chat + PDF viewer
- **Backend**: FastAPI serving the chat API and PDF files from Unity Catalog volumes
- **Agent**: `databricks-claude-sonnet-4-6` via Foundation Model API with a `search_documents` tool
- **Search**: Databricks Vector Search with per-document summary embeddings (`databricks-gte-large-en`)
- **Deployment**: Databricks App on workspace `fevm-morgan-stable-classic-6df0yw`

## Project Structure

```
doc_finder/
├── app.yaml                     # Databricks App config
├── requirements.txt             # Python dependencies
├── backend/
│   ├── main.py                  # FastAPI app (chat + PDF endpoints)
│   ├── agent.py                 # Chat agent (Foundation Model API + tool calling)
│   └── vector_search.py         # Vector Search query client
├── static/
│   └── index.html               # React frontend (CDN-loaded, no build step)
├── pipeline/
│   ├── 01_parse_docs.py         # Parse PDFs with ai_parse_document
│   ├── 02_summarize_docs.py     # Summarize docs with ai_query
│   ├── 03_create_vs_index.py    # Create Vector Search endpoint + index
│   └── 04_grant_app_permissions.py  # Grant app SP access to UC resources
└── raw_docs/                    # Source PDFs (also in UC volume)
```

## Setup

### Prerequisites

- Databricks CLI authenticated to the workspace
- Python with `databricks-sdk`, `databricks-sql-connector`, `databricks-vectorsearch`, `openai`

### 1. Run the data pipeline

```bash
python pipeline/01_parse_docs.py
python pipeline/02_summarize_docs.py
python pipeline/03_create_vs_index.py
```

### 2. Deploy the app

```bash
# Upload source to workspace
databricks workspace mkdirs /Workspace/Users/<you>/doc_finder_app --profile=<profile>
# Upload files: app.yaml, requirements.txt, backend/*, static/*

# Create and deploy
databricks apps create doc-finder --profile=<profile>
databricks apps deploy doc-finder --source-code-path /Workspace/Users/<you>/doc_finder_app --profile=<profile>
```

### 3. Configure resources

Add a SQL Warehouse resource to the app (key: `sql-warehouse`) via the Databricks Apps UI or API.

### 4. Grant permissions

```bash
python pipeline/04_grant_app_permissions.py
```

## Workspace Resources

| Resource | Value |
|----------|-------|
| Catalog | `morgan_stable_classic_6df0yw_catalog` |
| Schema | `doc_finder` |
| Volume | `raw_docs` |
| Vector Search Endpoint | `doc_finder_vs_endpoint` |
| Vector Search Index | `doc_summaries_index` |
| Foundation Model | `databricks-claude-sonnet-4-6` |
| Embedding Model | `databricks-gte-large-en` |
