# pipeline/02_summarize_docs.py
"""
Generate document summaries using ai_query for vector search indexing.

Configuration via environment variables (or defaults to dev):
    DATABRICKS_HOST, DATABRICKS_PROFILE, CATALOG, SCHEMA, WAREHOUSE_ID
"""
import os
from databricks import sql
from databricks.sdk.core import Config

CATALOG = os.getenv("CATALOG", "morgan_stable_classic_6df0yw_catalog")
SCHEMA = os.getenv("SCHEMA", "doc_finder")
WAREHOUSE_ID = os.getenv("WAREHOUSE_ID", "718f1b203cdea5c4")


def get_connection():
    cfg = Config(
        host=os.getenv("DATABRICKS_HOST", "https://fevm-morgan-stable-classic-6df0yw.cloud.databricks.com"),
        profile=os.getenv("DATABRICKS_PROFILE", "fe-vm-morgan-stable-classic-6df0yw"),
    )
    return sql.connect(
        server_hostname=cfg.host.replace("https://", ""),
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: cfg.authenticate,
    )


SUMMARY_PROMPT = """Summarize this document in under 200 words. Include:
- Document title or subject
- Document type (FDA clearance, research article, product brochure, clinical evidence, etc.)
- Key topics and findings
- Products, devices, or technologies mentioned
- Regulatory information if applicable

Document text:
"""


def run():
    conn = get_connection()
    cursor = conn.cursor()

    print(f"Creating {CATALOG}.{SCHEMA}.doc_summaries...")
    cursor.execute(f"""
        CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.doc_summaries (
            filename STRING,
            summary STRING,
            full_text STRING
        )
        USING DELTA
        TBLPROPERTIES (delta.enableChangeDataFeed = true)
    """)

    sql_safe_prompt = SUMMARY_PROMPT.replace("'", "''")

    print("Generating summaries via ai_query (this may take 1-4 minutes)...")
    cursor.execute(f"""
        INSERT INTO {CATALOG}.{SCHEMA}.doc_summaries
        SELECT
            filename,
            ai_query(
                'databricks-meta-llama-3-3-70b-instruct',
                CONCAT('{sql_safe_prompt}', LEFT(parsed_text, 8000))
            ) AS summary,
            parsed_text AS full_text
        FROM {CATALOG}.{SCHEMA}.parsed_docs
    """)

    cursor.execute(f"SELECT filename, summary FROM {CATALOG}.{SCHEMA}.doc_summaries")
    rows = cursor.fetchall()
    print(f"Summarized {len(rows)} documents:")
    for row in rows:
        print(f"\n--- {row[0]} ---")
        print(row[1][:200] + "...")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    run()
