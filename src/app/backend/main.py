# backend/main.py
"""
FastAPI application for Doc Finder.
Serves the chat API and PDF files from Unity Catalog volumes.
"""
import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from pydantic import BaseModel
from backend.agent import chat as agent_chat

import mlflow

logger = logging.getLogger(__name__)

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
    trace_id: str | None = None


class FeedbackRequest(BaseModel):
    trace_id: str
    thumbs_up: bool
    comment: str | None = None


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """Process a chat message through the document finder agent."""
    try:
        result = agent_chat(req.message, req.history)
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
