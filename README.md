# Doc Finder

Internal document search app for Integra LifeSciences. Employees describe the document they need via a chat interface, an AI agent searches the corpus using semantic search, and the best matching PDF is displayed in a side panel.

Deployed via **Databricks Asset Bundles (DABs)** for multi-environment portability.

## Architecture

- **Frontend**: React (CDN-loaded, single HTML file) with split-pane chat + PDF viewer
- **Backend**: FastAPI serving the chat API and PDF files from Unity Catalog volumes
- **Agent**: Foundation Model API — searches Vector Search, then responds with the best match in a single LLM call
- **Search**: Databricks Vector Search with per-document summary embeddings
- **Deployment**: Databricks Asset Bundles → Databricks App

### Data Flow

```
User describes document in chat
  → FastAPI receives POST /api/chat
  → Vector Search query over document summaries
  → Search results + user message sent to Foundation Model
  → Agent returns explanation + {filename, score}
  → Frontend renders response in chat + loads PDF via GET /api/docs/{filename}
  → PDF served from Unity Catalog volume via REST API
```

## Project Structure

```
doc_finder/
├── databricks.yml               # DABs bundle config (variables + targets)
├── resources/
│   └── doc_finder_app.yml       # App resource definition
├── src/
│   └── app/                     # App source (deployed to Databricks)
│       ├── app.yaml             # Databricks App runtime config
│       ├── requirements.txt     # Python dependencies
│       ├── backend/
│       │   ├── main.py          # FastAPI app (chat + PDF endpoints)
│       │   ├── agent.py         # Chat agent (single-call pattern)
│       │   └── vector_search.py # Vector Search query client
│       └── static/
│           └── index.html       # React frontend (CDN-loaded)
├── pipeline/
│   ├── 01_parse_docs.py         # Parse PDFs with ai_parse_document
│   ├── 02_summarize_docs.py     # Summarize docs with ai_query
│   ├── 03_create_vs_index.py    # Create Vector Search endpoint + index
│   └── 04_grant_app_permissions.py  # Grant app SP access to UC resources
├── scripts/
│   └── configure.py             # Generate app.yaml from bundle variables
├── .env.example                 # Template for pipeline env vars
└── raw_docs/                    # Source PDFs
```

## Bundle Variables

All environment-specific values are defined as variables in `databricks.yml`:

| Variable | Description | Default |
|----------|-------------|---------|
| `catalog` | Unity Catalog catalog | `morgan_stable_classic_6df0yw_catalog` |
| `schema` | Unity Catalog schema | `doc_finder` |
| `warehouse_id` | SQL Warehouse ID | `718f1b203cdea5c4` |
| `vs_endpoint_name` | Vector Search endpoint | `doc_finder_vs_endpoint` |
| `vs_index_name` | Vector Search index (full name) | `<catalog>.<schema>.doc_summaries_index` |
| `foundation_model` | LLM for chat agent | `databricks-claude-sonnet-4-6` |
| `embedding_model` | Embedding model for VS | `databricks-gte-large-en` |
| `volume_name` | Volume for PDF storage | `raw_docs` |

Override per target in `databricks.yml`:

```yaml
targets:
  prod:
    workspace:
      profile: prod-workspace-profile
    variables:
      catalog: prod_catalog
      warehouse_id: "abc123"
```

## Setup

### Prerequisites

- Databricks CLI v0.239.0+ (`databricks --version`)
- Authenticated CLI profile for the target workspace
- Python 3.11+ with: `databricks-sdk`, `databricks-sql-connector`, `databricks-vectorsearch`, `openai`

### 1. Configure for your target

```bash
# Generate app.yaml from bundle variables
python scripts/configure.py dev

# Or for a different target:
python scripts/configure.py prod
```

### 2. Set pipeline environment (for non-default targets)

```bash
cp .env.example .env
# Edit .env with your target workspace values
source .env
```

### 3. Upload PDFs and run the data pipeline

```bash
# Upload PDFs to the volume in your workspace, then:
python pipeline/01_parse_docs.py         # Parse PDFs (~2 min)
python pipeline/02_summarize_docs.py     # Summarize docs (~2 min)
python pipeline/03_create_vs_index.py    # Create VS index (~10-15 min)
```

### 4. Deploy the app via DABs

```bash
databricks bundle validate -t dev
databricks bundle deploy -t dev
databricks bundle run doc_finder -t dev
```

### 5. Grant permissions

After the app is created, get its service principal ID and grant UC access:

```bash
export APP_SP_ID=$(databricks apps get doc-finder-dev --output=json | python3 -c "import sys,json; print(json.load(sys.stdin)['service_principal_client_id'])")
python pipeline/04_grant_app_permissions.py
```

## Deploying to a New Workspace

1. Add a new target in `databricks.yml` with the workspace profile and variables
2. `python scripts/configure.py <target>` to generate app.yaml
3. `source .env` with target-specific values for pipeline scripts
4. Run the pipeline (steps 1-3 above)
5. `databricks bundle deploy -t <target>` + `databricks bundle run doc_finder -t <target>`
6. Grant permissions to the new app's service principal

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
   index = client.get_index("doc_finder_vs_endpoint", "<catalog>.<schema>.doc_summaries_index")
   index.sync()
   ```
