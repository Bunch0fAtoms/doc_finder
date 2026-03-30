# pipeline/02_summarize_docs.py
"""
Generate document summaries using ai_query for vector search indexing.
"""
from databricks import sql
from databricks.sdk.core import Config

CATALOG = "morgan_stable_classic_6df0yw_catalog"
SCHEMA = "doc_finder"
WAREHOUSE_ID = "718f1b203cdea5c4"

def get_connection():
    cfg = Config(
        host="https://fevm-morgan-stable-classic-6df0yw.cloud.databricks.com",
        profile="fe-vm-morgan-stable-classic-6df0yw",
    )
    return sql.connect(
        server_hostname=cfg.host.replace("https://", ""),
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: cfg.authenticate,
    )

# Single quotes doubled for SQL string safety
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

    print("Creating doc_summaries table...")
    cursor.execute(f"""
        CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.doc_summaries (
            filename STRING,
            summary STRING,
            full_text STRING
        )
        USING DELTA
        TBLPROPERTIES (delta.enableChangeDataFeed = true)
    """)

    # Escape single quotes in the prompt for SQL by doubling them
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
