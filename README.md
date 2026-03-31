# Doc Finder

Internal document search app for Integra LifeSciences. Employees describe the document they need via a chat interface, an AI agent searches the corpus using semantic search, and the best matching PDF is displayed in a side panel.

**Live app**: https://doc-finder-7474647784490566.aws.databricksapps.com

## Architecture

- **Frontend**: React (CDN-loaded, single HTML file) with split-pane chat + PDF viewer
- **Backend**: FastAPI serving the chat API and PDF files from Unity Catalog volumes
- **Agent**: `databricks-claude-sonnet-4-6` via Foundation Model API — searches Vector Search, then responds with the best match in a single LLM call
- **Search**: Databricks Vector Search with per-document summary embeddings (`databricks-gte-large-en`)
- **Deployment**: Databricks App on workspace `fevm-morgan-stable-classic-6df0yw`

### Data Flow

```
User describes document in chat
  → FastAPI receives POST /api/chat
  → Vector Search query over document summaries
  → Search results + user message sent to databricks-claude-sonnet-4-6
  → Agent returns explanation + {filename, score}
  → Frontend renders response in chat + loads PDF via GET /api/docs/{filename}
  → PDF served from Unity Catalog volume via REST API
```

## Project Structure

```
doc_finder/
├── app.yaml                     # Databricks App config
├── requirements.txt             # Python dependencies
├── backend/
│   ├── main.py                  # FastAPI app (chat + PDF endpoints)
│   ├── agent.py                 # Chat agent (Foundation Model API, single-call pattern)
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

- Databricks CLI authenticated to the workspace (`databricks auth login`)
- Python 3.11+ with packages: `databricks-sdk`, `databricks-sql-connector`, `databricks-vectorsearch`, `openai`

### 1. Upload PDFs to the volume

Upload PDFs to `/Volumes/morgan_stable_classic_6df0yw_catalog/doc_finder/raw_docs/` via the Databricks UI or CLI.

### 2. Run the data pipeline

Run scripts in order. Each connects to the SQL warehouse to execute queries.

```bash
python pipeline/01_parse_docs.py         # Extract text from PDFs (~2 min)
python pipeline/02_summarize_docs.py     # Generate summaries per doc (~2 min)
python pipeline/03_create_vs_index.py    # Create VS endpoint + index (~10-15 min)
```

### 3. Deploy the app

```bash
# Create workspace directory and upload app files
PROFILE=fe-vm-morgan-stable-classic-6df0yw
WS=/Workspace/Users/morgan.williams@databricks.com/doc_finder_app

databricks workspace mkdirs $WS --profile=$PROFILE
databricks workspace mkdirs $WS/backend --profile=$PROFILE
databricks workspace mkdirs $WS/static --profile=$PROFILE

for f in app.yaml requirements.txt backend/__init__.py backend/main.py backend/agent.py backend/vector_search.py static/index.html; do
  databricks workspace import $WS/$f --file=$f --format=AUTO --overwrite --profile=$PROFILE
done

# Create and deploy the app
databricks apps create doc-finder --profile=$PROFILE
# Wait for compute to become ACTIVE, then:
databricks apps deploy doc-finder --source-code-path $WS --profile=$PROFILE
```

### 4. Add SQL Warehouse resource

```bash
databricks api patch /api/2.0/apps/doc-finder --json '{
  "resources": [
    {
      "name": "sql-warehouse",
      "sql_warehouse": {
        "id": "718f1b203cdea5c4",
        "permission": "CAN_USE"
      }
    }
  ]
}' --profile=$PROFILE
```

Then redeploy:

```bash
databricks apps deploy doc-finder --source-code-path $WS --profile=$PROFILE
```

### 5. Grant permissions to the app service principal

Update the `APP_SP_ID` in `pipeline/04_grant_app_permissions.py` with the app's service principal ID (from `databricks apps get doc-finder`), then run:

```bash
python pipeline/04_grant_app_permissions.py
```

This grants the app's SP access to: catalog, schema, vector search index, and volume.

## Adding New Documents

1. Upload new PDFs to the volume
2. Re-run the pipeline:
   ```bash
   python pipeline/01_parse_docs.py
   python pipeline/02_summarize_docs.py
   ```
3. Sync the Vector Search index:
   ```python
   from databricks.vector_search.client import VectorSearchClient
   client = VectorSearchClient(...)
   index = client.get_index("doc_finder_vs_endpoint", "morgan_stable_classic_6df0yw_catalog.doc_finder.doc_summaries_index")
   index.sync()
   ```

## Workspace Resources

| Resource | Value |
|----------|-------|
| Catalog | `morgan_stable_classic_6df0yw_catalog` |
| Schema | `doc_finder` |
| Volume | `raw_docs` |
| Warehouse | `718f1b203cdea5c4` (Serverless Starter Warehouse) |
| Vector Search Endpoint | `doc_finder_vs_endpoint` |
| Vector Search Index | `doc_summaries_index` |
| Foundation Model | `databricks-claude-sonnet-4-6` |
| Embedding Model | `databricks-gte-large-en` |
| App URL | https://doc-finder-7474647784490566.aws.databricksapps.com |
