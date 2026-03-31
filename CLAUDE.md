# CLAUDE.md

## Project

Doc Finder — internal document search app for Integra LifeSciences. Chat with an AI agent to find the right PDF from a Unity Catalog volume.

## Tech Stack

- **Backend**: Python / FastAPI
- **Frontend**: Single-file React (CDN-loaded, no build step)
- **AI**: Databricks Foundation Model API (`databricks-claude-sonnet-4-6`)
- **Search**: Databricks Vector Search (per-document summary embeddings)
- **Data**: Unity Catalog (volumes, Delta tables)
- **Deployment**: Databricks Apps

## Workspace

- **Workspace**: `https://fevm-morgan-stable-classic-6df0yw.cloud.databricks.com`
- **CLI Profile**: `fe-vm-morgan-stable-classic-6df0yw`
- **Catalog**: `morgan_stable_classic_6df0yw_catalog`
- **Schema**: `doc_finder`
- **Warehouse ID**: `718f1b203cdea5c4`
- **App URL**: `https://doc-finder-7474647784490566.aws.databricksapps.com`

## Git

- GPG signing requires `pinentry-mac`. If GPG fails in subshells, use `git -c commit.gpgSign=false`.
- Remote: `https://github.com/Bunch0fAtoms/doc_finder`
- Enterprise Managed User — cannot create repos via CLI; create manually on GitHub first.

## Conventions

- All app code lives in this repo and is pushed to git before deploying.
- Deploy by uploading to `/Workspace/Users/morgan.williams@databricks.com/doc_finder_app` then `databricks apps deploy`.
- Pipeline scripts in `pipeline/` are run locally against the SQL warehouse (not on clusters).
- Use the single-call agent pattern (search first, then one LLM call) to stay under the 60s app proxy timeout.

## Key Decisions

- Per-document summary embeddings (not chunked) — optimized for document-level retrieval at 1M scale.
- CDN React frontend — avoids npm build step issues; single `static/index.html`.
- App service principal needs explicit UC grants (catalog, schema, index, volume) via `pipeline/04_grant_app_permissions.py`.
