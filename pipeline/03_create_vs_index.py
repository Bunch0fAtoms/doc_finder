# pipeline/03_create_vs_index.py
"""
Create Vector Search endpoint and Delta Sync index for document summaries.

Configuration via environment variables (or defaults to dev):
    DATABRICKS_HOST, DATABRICKS_PROFILE, CATALOG, SCHEMA,
    VS_ENDPOINT_NAME, EMBEDDING_MODEL
"""
import os
from databricks.vector_search.client import VectorSearchClient
from databricks.sdk.core import Config

CATALOG = os.getenv("CATALOG", "morgan_stable_classic_6df0yw_catalog")
SCHEMA = os.getenv("SCHEMA", "doc_finder")
VS_ENDPOINT_NAME = os.getenv("VS_ENDPOINT_NAME", "doc_finder_vs_endpoint")
VS_INDEX_NAME = f"{CATALOG}.{SCHEMA}.doc_summaries_index"
SOURCE_TABLE = f"{CATALOG}.{SCHEMA}.doc_summaries"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "databricks-gte-large-en")


def run():
    cfg = Config(
        host=os.getenv("DATABRICKS_HOST", "https://fevm-morgan-stable-classic-6df0yw.cloud.databricks.com"),
        profile=os.getenv("DATABRICKS_PROFILE", "fe-vm-morgan-stable-classic-6df0yw"),
    )
    token = cfg.authenticate()["Authorization"].replace("Bearer ", "")
    client = VectorSearchClient(
        workspace_url=cfg.host,
        personal_access_token=token,
    )

    try:
        client.get_endpoint(VS_ENDPOINT_NAME)
        print(f"Endpoint '{VS_ENDPOINT_NAME}' already exists.")
    except Exception:
        print(f"Creating endpoint '{VS_ENDPOINT_NAME}'...")
        client.create_endpoint_and_wait(
            name=VS_ENDPOINT_NAME,
            endpoint_type="STANDARD",
        )
        print("Endpoint created.")

    try:
        client.get_index(
            endpoint_name=VS_ENDPOINT_NAME,
            index_name=VS_INDEX_NAME,
        )
        print(f"Index '{VS_INDEX_NAME}' already exists.")
    except Exception:
        print(f"Creating index '{VS_INDEX_NAME}'...")
        client.create_delta_sync_index_and_wait(
            endpoint_name=VS_ENDPOINT_NAME,
            index_name=VS_INDEX_NAME,
            source_table_name=SOURCE_TABLE,
            primary_key="filename",
            embedding_source_column="summary",
            embedding_model_endpoint_name=EMBEDDING_MODEL,
            pipeline_type="TRIGGERED",
        )
        print("Index created and synced.")

    index = client.get_index(
        endpoint_name=VS_ENDPOINT_NAME,
        index_name=VS_INDEX_NAME,
    )
    results = index.similarity_search(
        query_text="FDA medical device clearance",
        columns=["filename", "summary"],
        num_results=3,
    )
    print("\nTest query: 'FDA medical device clearance'")
    for doc in results.get("result", {}).get("data_array", []):
        print(f"  - {doc[0]} (score: {doc[-1]:.3f})")


if __name__ == "__main__":
    run()
