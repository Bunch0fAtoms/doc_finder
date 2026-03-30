# backend/main.py
"""
FastAPI application for Doc Finder.
Serves the chat API and PDF files from Unity Catalog volumes.
"""
import os
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from pydantic import BaseModel
from databricks.sdk import WorkspaceClient
from backend.agent import chat as agent_chat

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


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """Process a chat message through the document finder agent."""
    try:
        result = agent_chat(req.message, req.history)
        return ChatResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/docs/{filename}")
async def get_document(filename: str):
    """Serve a PDF from the Unity Catalog volume."""
    try:
        w = WorkspaceClient()
        file_path = f"{VOLUME_PATH}/{filename}"
        resp = w.files.download(file_path)
        content = resp.read()
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Document not found: {filename}")


# Serve React static files (built frontend)
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
