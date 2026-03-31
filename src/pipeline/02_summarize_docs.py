# src/pipeline/02_summarize_docs.py
"""
Generate document summaries using ai_query for vector search indexing.

DABs:  databricks bundle run data_pipeline (runs all 3 steps)
Local: python src/pipeline/02_summarize_docs.py --catalog=X --schema=X --warehouse-id=X
"""
from databricks import sql
from databricks.sdk.core import Config
from _config import parse_config

cfg = parse_config("catalog", "schema", "warehouse_id")
CATALOG = cfg["catalog"]
SCHEMA = cfg["schema"]
WAREHOUSE_ID = cfg["warehouse_id"]

SUMMARY_PROMPT = """Summarize this document in under 200 words. Include:
- Document title or subject
- Document type (FDA clearance, research article, product brochure, clinical evidence, etc.)
- Key topics and findings
- Products, devices, or technologies mentioned
- Regulatory information if applicable

Document text:
"""


def get_connection():
    sdk_cfg = Config()
    return sql.connect(
        server_hostname=sdk_cfg.host.replace("https://", ""),
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: sdk_cfg.authenticate,
    )


def main():
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
    main()
