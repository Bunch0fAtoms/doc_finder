# backend/main.py
"""
FastAPI application for Doc Finder.
Serves the chat API and PDF files from Unity Catalog volumes.
"""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from pydantic import BaseModel
import mlflow

from backend.agent import chat as agent_chat

logger = logging.getLogger(__name__)


def _get_deployment_version() -> str:
    """Get a version string from the Databricks App deployment ID, or fall back to APP_VERSION."""
    # DATABRICKS_APP_NAME must match bundle app name (doc-finder-<target>) for Apps API.
    # MLFLOW_APP_NAME is an optional label (e.g. from git branch via configure.py) for the version prefix.
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        api_app = os.getenv("DATABRICKS_APP_NAME") or os.getenv("MLFLOW_APP_NAME", "doc-finder-dev")
        app = w.apps.get(api_app)
        deploy_id = app.active_deployment.deployment_id
        label = os.getenv("MLFLOW_APP_NAME") or api_app
        return f"{label}-{deploy_id[:12]}"
    except Exception:
        pass
    # Fall back to APP_VERSION env var (set by configure.py)
    return os.getenv("APP_VERSION", "dev")


def _init_mlflow_logged_model() -> None:
    """
    Link traces to an MLflow LoggedModel so the Version column resolves in the UI.

    Prefer MLFLOW_ACTIVE_MODEL_ID when a fixed model id is injected at deploy time.
    Otherwise call mlflow.set_active_model(name=...) once per process — see:
    https://docs.databricks.com/aws/en/mlflow3/genai/prompt-version-mgmt/version-tracking/track-application-versions-with-mlflow
    """
    mlflow.set_tracking_uri("databricks")
    mlflow.set_experiment(os.getenv("MLFLOW_EXPERIMENT", "/Shared/doc-finder"))

    if os.getenv("MLFLOW_ACTIVE_MODEL_ID", "").strip():
        logger.info("MLflow trace version: using MLFLOW_ACTIVE_MODEL_ID from environment")
        return

    version = _get_deployment_version()
    # LoggedModel names must be filesystem/registry safe
    safe = "".join(c if c.isalnum() or c in "-_." else "-" for c in version)
    try:
        active = mlflow.set_active_model(name=safe)
        mid = getattr(active, "model_id", active)
        logger.info("MLflow LoggedModel active name=%r model_id=%r", safe, mid)
    except Exception:
        logger.exception("mlflow.set_active_model failed; Version column may show Error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_mlflow_logged_model()
    yield


app = FastAPI(title="Doc Finder", lifespan=lifespan)

CATALOG = os.getenv("CATALOG", "morgan_stable_classic_6df0yw_catalog")
SCHEMA = os.getenv("SCHEMA", "doc_finder")
VOLUME = os.getenv("VOLUME", "raw_docs")
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    filename: str | None = None
    score: float | None = None
    trace_id: str | None = None


class FeedbackRequest(BaseModel):
    trace_id: str
    thumbs_up: bool
    comment: str | None = None


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """Process a chat message through the document finder agent."""
    try:
        result = agent_chat(req.message, req.history, session_id=req.session_id)
        return ChatResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/feedback")
async def feedback_endpoint(req: FeedbackRequest):
    """Record thumbs up/down feedback on a trace."""
    try:
        mlflow.set_tracking_uri("databricks")
        client = mlflow.MlflowClient()
        client.set_trace_tag(req.trace_id, "feedback.thumbs_up", str(req.thumbs_up))
        if req.comment:
            client.set_trace_tag(req.trace_id, "feedback.comment", req.comment)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Failed to set feedback tag: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/docs/{filename}")
async def get_document(filename: str):
    """Serve a PDF from the Unity Catalog volume."""
    import requests
    from databricks.sdk.core import Config

    try:
        cfg = Config()
        headers = cfg.authenticate()
        file_path = f"{VOLUME_PATH}/{filename}"
        url = f"{cfg.host}/api/2.0/fs/files{file_path}"
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code,
                detail=f"Failed to download {filename}: {resp.text[:200]}",
            )
        return Response(
            content=resp.content,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error serving {filename}: {str(e)}")


# Serve React static files (built frontend)
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
