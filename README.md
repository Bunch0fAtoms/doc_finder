# Doc Finder

Internal document search app for Integra LifeSciences. Employees describe the document they need via a chat interface, an AI agent searches the corpus using **hybrid search** (semantic + exact keyword), and the best matching PDF is displayed in a side panel.

Deployed via **Databricks Asset Bundles (DABs)** for multi-environment portability.

## Architecture

![System Architecture](docs/architecture.png)

- **Databricks App**: React frontend (CDN-loaded) + FastAPI backend, deployed as a single Databricks App
- **FastAPI Backend**: Orchestrates all calls — query classification, search dispatch, response generation, and PDF serving
- **Claude Haiku 4.5**: Query classifier — returns semantic query, keyword terms, and reasoning to FastAPI
- **Claude Sonnet 4.6**: Response generator — receives merged search results from FastAPI, returns answer + filename
- **Vector Search**: Databricks Vector Search in hybrid mode (vector + keyword) over summary embeddings (`databricks-gte-large-en`)
- **SQL Keyword Search**: Punctuation-normalized `ILIKE` on the `doc_summaries.plain_text` column via SQL Warehouse
- **Deployment**: Databricks Asset Bundles → Databricks App

### Hybrid Search

The search operates on four layers:

1. **Query understanding (Claude Haiku 4.5)** — classifies the user's query, rephrases it for better semantic matching, and extracts keyword terms for exact text search. Uses a fast, non-thinking model to minimize latency.
2. **Vector Search (hybrid mode)** — combines vector similarity + keyword matching within the VS index on document summaries, using the classifier's rephrased query
3. **SQL ILIKE** — punctuation-normalized text match on `plain_text` column (extracted content from text, table, title, and section header elements). Strips `: ; - space` from both the search term and document text so `45:28-33` matches `2006;45:28-33`.
4. **Response (Claude Sonnet 4.6)** — receives merged results from FastAPI along with the classifier's reasoning for context, prioritizes keyword matches for identifier queries, and explains why the document matches

| Query Type | Example | Search Path |
|-----------|---------|-------------|
| **Semantic** | "Find the wound healing brochure" | Haiku rephrases → VS hybrid on summaries |
| **Exact identifier** | "Find document K243531" | Haiku extracts terms → VS hybrid + SQL ILIKE |
| **Citation/partial** | "45:28-33" | Haiku extracts keyword terms → VS hybrid + normalized SQL ILIKE |

#### Why keyword search matters

Standard vector search encodes *meaning*, not literal strings. An FDA K-number like `K243531` or a citation like `45:28-33` has no semantic meaning to an embedding model — it's just noise. The keyword layer guarantees these exact matches surface even when vector search misses entirely.

#### Punctuation normalization

Medical documents contain identifiers with inconsistent formatting — colons, semicolons, hyphens, and spaces vary between documents. The keyword search strips `: ; - space` from **both** the search term and the stored document text before comparing:

| User types | Stored in document | Normalized | Match? |
|---|---|---|---|
| `45:28-33` | `2006;45:28-33` | `452833` / `2006452833` | Yes |
| `K243531` | `K243531` | `k243531` / `k243531` | Yes |
| `510(k)` | `510 (k)` | `510(k)` / `510(k)` | Yes |

The SQL applies this normalization inline:
```sql
REPLACE(REPLACE(REPLACE(REPLACE(LOWER(plain_text), ':', ''), ';', ''), '-', ''), ' ', '')
LIKE '%452833%'
```

#### What `plain_text` contains

The pipeline extracts only **text, table, title, and section header** elements from parsed PDF content. This gives clean searchable text without layout noise, so identifiers embedded in tables or headings are still findable.

### Data Flow

```
User describes document in chat
  → React Frontend sends POST /api/chat to FastAPI
  → FastAPI calls Claude Haiku 4.5 → returns {semantic_query, keyword_terms, reasoning}
  → FastAPI dispatches searches in parallel:
      • Vector Search hybrid query on doc_summaries.summary (always)
      • SQL ILIKE on doc_summaries.plain_text (if keyword_terms extracted)
  → FastAPI merges and deduplicates results by filename
  → FastAPI sends combined results + reasoning + user message to Claude Sonnet 4.6
  → Sonnet returns explanation + {filename, score} to FastAPI
  → FastAPI returns response to Frontend
  → Frontend renders response in chat + loads PDF via GET /api/docs/{filename}
  → FastAPI fetches PDF from Unity Catalog volume and returns it
```

### Data Pipeline

```
data_pipeline (DABs job, on Databricks):
  → Step 0: Create UC schema + volume, upload PDFs from raw_docs/ (skips existing)
             Set skip_upload variable to "true" if you land PDFs via your own pipeline
  → Step 1: ai_parse_document extracts text from each PDF
  → Step 2: ai_query (Gemini 2.5 Pro, 100K char input) generates ~200-word summary per document;
           plain_text extracted from content elements (text, table, title, section_header)
  → Step 3: Vector Search Delta Sync index embeds summaries with databricks-gte-large-en
  → Output: doc_summaries table (filename, summary, full_text, plain_text) + VS index
```

## Project Structure

```
doc_finder/
├── databricks.yml               # DABs bundle config (variables + targets)
├── resources/
│   ├── doc_finder_app.yml       # App resource (+ SQL warehouse for keyword search)
│   └── pipeline_jobs.yml        # Data pipeline job (4 sequential tasks)
├── src/
│   ├── app/                     # App source (deployed to Databricks)
│   │   ├── app.yaml             # Databricks App runtime config
│   │   ├── requirements.txt     # Python dependencies
│   │   ├── backend/
│   │   │   ├── main.py          # FastAPI app (chat + PDF endpoints)
│   │   │   ├── agent.py         # Hybrid search agent (Haiku classifier + Claude response)
│   │   │   ├── vector_search.py # Vector Search query client
│   │   │   └── keyword_search.py# SQL ILIKE search on plain text
│   │   └── static/
│   │       └── index.html       # React frontend (CDN-loaded)
│   └── pipeline/                # Pipeline scripts (run as DABs job tasks)
│       ├── _config.py           # Shared config parser (CLI args + env vars)
│       ├── 00_upload_docs.py    # Create schema/volume + upload PDFs
│       ├── 01_parse_docs.py     # Parse PDFs with ai_parse_document
│       ├── 02_summarize_docs.py # Summarize with Gemini 2.5 Pro (100K input)
│       ├── 03_create_vs_index.py# Create VS endpoint + index
│       └── 04_grant_app_permissions.py
├── scripts/
│   └── configure.py             # Generate app.yaml (--name flag or auto from git branch)
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
| `foundation_model` | LLM for chat response agent | `databricks-claude-sonnet-4-6` |
| `classifier_model` | LLM for query classification | `databricks-claude-haiku-4-5` |
| `summarization_model` | LLM for document summarization (pipeline) | `databricks-gemini-2-5-pro` |
| `embedding_model` | Embedding model for VS | `databricks-gte-large-en` |
| `volume_name` | Volume for PDF storage | `raw_docs` |
| `skip_upload` | Skip PDF upload step (use your own pipeline) | `false` |

Three targets are pre-configured in `databricks.yml`:

| Target | Workspace | Purpose |
|--------|-----------|---------|
| `databricks-dev` | FEVM (Morgan) | Internal dev/test |
| `databricks-demo` | e2-demo-field-eng | Client-facing demo |
| `integra-dev` | *Client workspace* | Client's own dev environment — update placeholder values |

To add a new target, copy the `integra-dev` block and fill in your workspace details.

## Setup

### Prerequisites

- Databricks CLI v0.239.0+ (`databricks --version`)
- Authenticated CLI profile for the target workspace
- Python 3.11+ with: `databricks-sdk`, `databricks-sql-connector`, `databricks-vectorsearch`, `openai`

### 1. Configure for your target

```bash
python scripts/configure.py databricks-demo
```

This generates `app.yaml` with the correct env vars for the target. **`DATABRICKS_APP_NAME`** (and bundle `app_name`) must be identical.

By default, the app name is derived from the **sanitized git branch** (`doc-finder-<branch>`), capped at 30 characters. To set an explicit name (recommended for production):

```bash
python scripts/configure.py databricks-demo --name=doc-finder
```

You can also set it via the `APP_NAME` environment variable.

**Important:** pass the same `app_name` into the bundle as `configure.py` printed. If you omit `--var app_name=...`, the bundle defaults to `doc-finder` and the running app’s `DATABRICKS_APP_NAME` will not match the deployed app (Apps API / MLflow version lookups break).

### 2. Deploy everything via DABs

Run `configure.py` first, then use the `app_name` it prints for all subsequent commands.

```bash
# 1. Generate app.yaml (use --name for explicit app name, or let it derive from git branch)
python scripts/configure.py databricks-demo --name=doc-finder

# 2. Deploy bundle resources + upload app source
databricks bundle deploy -t databricks-demo --var app_name=doc-finder

# 3. Grant table permissions (required — DABs can't grant TABLE/SELECT via uc_securable)
python src/pipeline/04_grant_app_permissions.py \
  --catalog=morgancatalog --schema=doc_finder \
  --warehouse-id=4b9b953939869799 --volume=raw_docs \
  --app-name=doc-finder

# 4. Run the data pipeline (Upload → Parse → Summarize → Index)
databricks bundle run data_pipeline -t databricks-demo

# 5. Start the app
databricks bundle run doc_finder -t databricks-demo --var app_name=doc-finder
```

### 3. Permissions

Most permissions are declared in `doc_finder_app.yml` and granted automatically at deploy time:

| Resource | Permission | Granted by | Purpose |
|----------|-----------|------------|---------|
| SQL Warehouse | CAN_USE | DABs (auto) | Keyword search queries |
| Sonnet endpoint | CAN_QUERY | DABs (auto) | Response generation |
| Haiku endpoint | CAN_QUERY | DABs (auto) | Query classification |
| UC Volume (raw_docs) | READ_VOLUME | DABs (auto) | PDF serving |
| doc_summaries table | SELECT | **Manual** (grant script) | Keyword search data |
| VS index table | SELECT | **Manual** (grant script) | Semantic / hybrid search |
| USE_CATALOG / USE_SCHEMA | — | **Manual** (grant script) | Required for all UC access |

**Note:** DABs `uc_securable` only supports VOLUME types. TABLE/SELECT grants and USE_CATALOG/USE_SCHEMA must be applied via `04_grant_app_permissions.py` after the first deploy.

## Deploying to a New Workspace

### Prerequisites

| Resource | Why | How |
|----------|-----|-----|
| **SQL Warehouse** | Used by the pipeline (parsing, summarization) and the app (keyword search) | Create in workspace UI; copy the ID from the warehouse settings page |
| **Databricks CLI profile** | The `profile` field in `databricks.yml` must match an authenticated profile in `~/.databrickscfg` | `databricks auth login --host https://<workspace>.cloud.databricks.com --profile <name>` |

Everything else (catalog, schema, volume, tables, Vector Search endpoint + index) is created automatically by the data pipeline.

### Step 1: Add a target in `databricks.yml`

Copy the `integra-dev` block and fill in your workspace values:

```yaml
  my-workspace:
    mode: development
    workspace:
      profile: <your-cli-profile>            # must match databricks auth login --profile
      host: https://<your-workspace>.cloud.databricks.com
    variables:
      catalog: <your_catalog>                # Unity Catalog catalog (must exist or be creatable)
      schema: doc_finder
      warehouse_id: "<your_warehouse_id>"    # from the prerequisite step above
      vs_endpoint_name: doc_finder_vs_endpoint
      vs_index_name: <your_catalog>.doc_finder.doc_summaries_index
      foundation_model: databricks-claude-sonnet-4-6   # or databricks-gemini-2-5-flash
      classifier_model: databricks-claude-haiku-4-5
      summarization_model: databricks-gemini-2-5-pro
      embedding_model: databricks-gte-large-en
      volume_name: raw_docs
```

### Step 2: Generate app config

```bash
python scripts/configure.py my-workspace --name=doc-finder
```

### Step 3: Deploy bundle

```bash
databricks bundle deploy -t my-workspace --var app_name=doc-finder
```

This uploads the app source to the workspace and creates the app resource. DABs automatically grants the app service principal access to the SQL warehouse, serving endpoints, and UC volume.

### Step 4: Grant table permissions (one-time after first deploy)

DABs cannot grant TABLE/SELECT permissions — only VOLUME types are supported. Run the grant script to give the app service principal access to the doc_summaries table, VS index, and parent catalog/schema:

```bash
python src/pipeline/04_grant_app_permissions.py \
  --catalog=<your_catalog> \
  --schema=doc_finder \
  --warehouse-id=<your_warehouse_id> \
  --volume=raw_docs \
  --app-name=doc-finder
```

### Step 5: Run the data pipeline

This uploads PDFs from `raw_docs/`, parses them, generates summaries, and creates the Vector Search index:

```bash
databricks bundle run data_pipeline -t my-workspace
```

### Step 6: Start the app

```bash
databricks bundle run doc_finder -t my-workspace --var app_name=doc-finder
```

The app URL will be printed when the command completes.

### Notes

- **Foundation model choice:** If the workspace FMAPI guardrail blocks medical content (we saw this on the shared e2-demo workspace), switch `foundation_model` to `databricks-gemini-2-5-flash`.
- **Re-deploying:** After the first deploy, you only need steps 2-3 and 6 for code changes. Step 4 (grants) and step 5 (pipeline) are one-time unless you change the catalog/schema or add new documents.

## Adding New Documents

1. Upload new PDFs to the volume
2. Re-run the pipeline:
   ```bash
   databricks bundle run data_pipeline -t databricks-demo
   ```
   This re-parses all PDFs, regenerates summaries, and syncs the VS index.

## Observability

All agent interactions are traced via **MLflow** to the `/Shared/doc-finder` experiment. Each request produces a trace with spans for:

- **chat** (AGENT) — top-level span with user message, response, and extracted filename
- **classify_query** (CHAIN) — Claude Haiku 4.5 classification: semantic_query, keyword_terms, reasoning
- **vector_search** (RETRIEVER) — Vector Search results with scores
- **keyword_search** (RETRIEVER) — SQL ILIKE results (if keyword terms were extracted)
- **OpenAI calls** (auto-traced) — raw LLM request/response for both Haiku and Claude Sonnet

Users can give thumbs up/down on each response with an optional comment. Feedback is stored as `feedback.thumbs_up` and `feedback.comment` tags on the MLflow trace.

- **Session** — frontend generates a UUID per browser tab, set via `mlflow.trace.session` metadata. Groups multi-turn conversations.
- **Version** — set via MLflow LoggedModel on app startup. Automatically derived from the Databricks App deployment ID (no manual step needed).

View traces in the Databricks workspace under **Experiments → /Shared/doc-finder**.

## Databricks Resources Used

| Resource | Used By | Purpose |
|----------|---------|---------|
| **SQL Warehouse** | Pipeline + App (keyword search) | `ai_parse_document`, `ai_query`, `ILIKE` on plain text |
| **Vector Search Endpoint** | App (semantic search) | Similarity search over document summaries |
| **Foundation Model API** | App | Claude Haiku 4.5 (query classification), Claude Sonnet 4.6 (chat agent) |
| **Foundation Model API** | Pipeline | Gemini 2.5 Pro (document summarization via `ai_query`) |
| **Unity Catalog Volume** | Pipeline + App | PDF storage and serving |
| **MLflow Experiment** | App | Trace storage for all agent interactions (`/Shared/doc-finder`) |
| **Databricks App** | End users | FastAPI + React frontend |
