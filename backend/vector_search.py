# backend/vector_search.py
"""
Vector Search client for querying document summaries.
"""
import os
from databricks.vector_search.client import VectorSearchClient
from databricks.sdk.core import Config


VS_ENDPOINT_NAME = os.getenv("VS_ENDPOINT_NAME", "doc_finder_vs_endpoint")
VS_INDEX_NAME = os.getenv(
    "VS_INDEX_NAME",
    "morgan_stable_classic_6df0yw_catalog.doc_finder.doc_summaries_index",
)


def _get_client():
    cfg = Config()
    token = cfg.authenticate()["Authorization"].replace("Bearer ", "")
    return VectorSearchClient(
        workspace_url=cfg.host,
        personal_access_token=token,
    )


def search_documents(query: str, num_results: int = 5) -> list[dict]:
    """
    Search document summaries by semantic similarity.

    Returns list of dicts with keys: filename, summary, score
    """
    client = _get_client()
    index = client.get_index(
        endpoint_name=VS_ENDPOINT_NAME,
        index_name=VS_INDEX_NAME,
    )
    results = index.similarity_search(
        query_text=query,
        columns=["filename", "summary"],
        num_results=num_results,
    )
    data = results.get("result", {}).get("data_array", [])
    return [
        {"filename": row[0], "summary": row[1], "score": row[2]}
        for row in data
    ]
