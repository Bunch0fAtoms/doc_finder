# Doc Finder

Internal document search app for Integra LifeSciences. Employees describe the document they need via a chat interface, an AI agent searches the corpus using **hybrid search** (semantic + exact keyword), and the best matching PDF is displayed in a side panel.

Deployed via **Databricks Asset Bundles (DABs)** for multi-environment portability.

## Architecture

- **Frontend**: React (CDN-loaded, single HTML file) with split-pane chat + PDF viewer
- **Backend**: FastAPI serving the chat API and PDF files from Unity Catalog volumes
- **Agent**: `databricks-claude-sonnet-4-6` via Foundation Model API — hybrid search with single LLM call
- **Vector Search**: Databricks Vector Search in hybrid mode (vector + keyword) over summary embeddings (`databricks-gte-large-en`)
- **SQL Keyword Search**: SQL `ILIKE` on full extracted text for exact identifiers (SKUs, part numbers, regulatory codes)
- **Deployment**: Databricks Asset Bundles → Databricks App

### Hybrid Search

The agent automatically selects the right search strategy based on the user's query:

The search operates on three layers:

1. **Vector Search (hybrid mode)** — combines vector similarity + keyword matching within the VS index on document summaries
2. **SQL ILIKE** — exact text match on full extracted document text (for SKUs, part numbers, regulatory codes)
3. **Agent intelligence** — Claude Sonnet 4.6 merges results, prioritizes keyword matches for identifier queries, and explains why the document matches

| Query Type | Example | Search Path |
|-----------|---------|-------------|
| **Semantic** | "Find the wound healing brochure" | VS hybrid on summaries |
| **Exact identifier** | "Find document K243531" | VS hybrid + SQL ILIKE on full text |
| **Mixed** | "FDA clearance for product code JXG" | VS hybrid + SQL ILIKE, merged |

Identifier detection uses regex patterns matching SKUs, part numbers, CFR codes, and alphanumeric product codes.

### Data Flow

```
User describes document in chat
  → FastAPI receives POST /api/chat
  → Agent detects identifiers in message (regex)
  → If identifiers found: SQL ILIKE on doc_summaries.full_text (keyword search)
  → Always: Vector Search hybrid query on doc_summaries.summary (vector + keyword)
  → Results merged, deduplicated by filename
  → Combined results + user message sent to Claude Sonnet 4.6
  → Agent returns explanation + {filename, score}
  → Frontend renders response in chat + loads PDF via GET /api/docs/{filename}
  → PDF served from Unity Catalog volume via REST API
```

### Data Pipeline

```
UC Volume (raw PDFs)
  → Step 1: ai_parse_document extracts text from each PDF
  → Step 2: ai_query (Gemini 2.5 Pro, 100K char input) generates ~200-word summary per document
  → Step 3: Vector Search Delta Sync index embeds summaries with databricks-gte-large-en
  → Output: doc_summaries table (filename, summary, full_text) + VS index
```

## Project Structure

```
doc_finder/
├── databricks.yml               # DABs bundle config (variables + targets)
├── resources/
│   ├── doc_finder_app.yml       # App resource (+ SQL warehouse for keyword search)
│   └── pipeline_jobs.yml        # Data pipeline job (3 sequential tasks)
├── src/
│   ├── app/                     # App source (deployed to Databricks)
│   │   ├── app.yaml             # Databricks App runtime config
│   │   ├── requirements.txt     # Python dependencies
│   │   ├── backend/
│   │   │   ├── main.py          # FastAPI app (chat + PDF endpoints)
│   │   │   ├── agent.py         # Hybrid search agent (semantic + keyword)
│   │   │   ├── vector_search.py # Vector Search query client
│   │   │   └── keyword_search.py# SQL ILIKE search on full text
│   │   └── static/
│   │       └── index.html       # React frontend (CDN-loaded)
│   └── pipeline/                # Pipeline scripts (run as DABs job tasks)
│       ├── _config.py           # Shared config parser (CLI args + env vars)
│       ├── 01_parse_docs.py     # Parse PDFs with ai_parse_document
│       ├── 02_summarize_docs.py # Summarize with Gemini 2.5 Pro (100K input)
│       ├── 03_create_vs_index.py# Create VS endpoint + index
│       └── 04_grant_app_permissions.py
├── scripts/
│   └── configure.py             # Generate app.yaml from bundle variables
├── .env.example                 # Template for local pipeline runs
└── raw_docs/                    # Source PDFs
```

## Bundle Variables

All environment-specific values are defined as variables in `databricks.yml`:

| Variable | Description | Default |
|----------|-------------|---------|
| `catalog` | Unity Catalog catalog | `morgan_stable_classic_6df0yw_catalog` |
| `schema` | Unity Catalog schema | `doc_finder` |
| `warehouse_id` | SQL Warehouse ID (pipeline + keyword search) | `718f1b203cdea5c4` |
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
python scripts/configure.py dev
```

### 2. Deploy everything via DABs

```bash
databricks bundle validate -t dev
databricks bundle deploy -t dev
databricks bundle run data_pipeline -t dev   # Parse → Summarize → Index
databricks bundle run doc_finder -t dev      # Start app
```

### 3. Grant permissions

```bash
APP_SP_ID=$(databricks apps get doc-finder-dev --output=json \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['service_principal_client_id'])")

python src/pipeline/04_grant_app_permissions.py \
  --catalog=morgan_stable_classic_6df0yw_catalog \
  --schema=doc_finder \
  --warehouse-id=718f1b203cdea5c4 \
  --app-sp-id=$APP_SP_ID
```

Grants: USE_CATALOG, USE_SCHEMA, SELECT on VS index, SELECT on doc_summaries table, READ_VOLUME.

## Deploying to a New Workspace

1. Add a new target in `databricks.yml` with the workspace profile and variable overrides
2. `python scripts/configure.py <target>` to generate `src/app/app.yaml`
3. `databricks bundle deploy -t <target>`
4. `databricks bundle run data_pipeline -t <target>`
5. `databricks bundle run doc_finder -t <target>`
6. Grant permissions to the new app's service principal

## Adding New Documents

1. Upload new PDFs to the volume
2. Re-run the pipeline:
   ```bash
   databricks bundle run data_pipeline -t dev
   ```
   This re-parses all PDFs, regenerates summaries, and syncs the VS index.

## Databricks Resources Used

| Resource | Used By | Purpose |
|----------|---------|---------|
| **SQL Warehouse** | Pipeline + App (keyword search) | `ai_parse_document`, `ai_query`, `ILIKE` queries |
| **Vector Search Endpoint** | App (semantic search) | Similarity search over document summaries |
| **Foundation Model API** | Pipeline + App | Gemini 2.5 Pro (summarization), Claude Sonnet 4.6 (chat agent) |
| **Unity Catalog Volume** | Pipeline + App | PDF storage and serving |
| **Databricks App** | End users | FastAPI + React frontend |
