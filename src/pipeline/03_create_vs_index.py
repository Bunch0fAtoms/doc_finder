# src/pipeline/03_create_vs_index.py
"""
Create Vector Search endpoint and Delta Sync index for document summaries.

DABs:  databricks bundle run data_pipeline (runs all 3 steps)
Local: python src/pipeline/03_create_vs_index.py --catalog=X --schema=X --vs-endpoint-name=X --embedding-model=X
"""
from databricks.vector_search.client import VectorSearchClient
from databricks.sdk.core import Config
from _config import parse_config

cfg = parse_config("catalog", "schema", "vs_endpoint_name", "embedding_model")
CATALOG = cfg["catalog"]
SCHEMA = cfg["schema"]
VS_ENDPOINT_NAME = cfg["vs_endpoint_name"]
VS_INDEX_NAME = f"{CATALOG}.{SCHEMA}.doc_summaries_index"
SOURCE_TABLE = f"{CATALOG}.{SCHEMA}.doc_summaries"
EMBEDDING_MODEL = cfg["embedding_model"]


def main():
    sdk_cfg = Config()
    token = sdk_cfg.authenticate()["Authorization"].replace("Bearer ", "")
    client = VectorSearchClient(
        workspace_url=sdk_cfg.host,
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
    main()
