# Thumbs Up/Down Feedback Design

**Date:** 2026-04-09
**Branch:** improving_ux

## Goal

Let users rate whether the agent's document recommendation was correct (or flag when no document was found). Feedback is attached to the MLflow trace and synced to Delta for SQL querying.

## Changes

### Frontend (src/app/static/index.html)

- Add thumbs up/down buttons below each agent response
- Always visible (even when no document recommended — a failed search is useful feedback)
- On click, send `POST /api/feedback` with `{trace_id, thumbs_up: bool}`
- Disable both buttons after one is clicked (one vote per response)

### Backend (src/app/backend/main.py)

- New `POST /api/feedback` endpoint
- Accepts `{trace_id: str, thumbs_up: bool}`
- Uses MLflow SDK to set tag `feedback.thumbs_up` on the trace

### Agent (src/app/backend/agent.py)

- `chat()` returns `trace_id` extracted from the current active span
- Uses `mlflow.get_current_active_span()` to get the trace/request ID

### Response Model

`ChatResponse` adds `trace_id: str | None` field.

## Data Flow

```
User clicks thumbs down
  → POST /api/feedback {trace_id: "abc123", thumbs_up: false}
  → Backend sets tag on MLflow trace
  → Synced to Delta → queryable via SQL
```

## No New Dependencies

- MLflow SDK already in requirements
- No new tables or permissions needed
- Feedback queryable via existing UC trace sync
