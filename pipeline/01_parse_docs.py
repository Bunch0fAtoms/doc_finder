# pipeline/01_parse_docs.py
"""
Parse PDFs from Unity Catalog volume using ai_parse_document.

Configuration via environment variables (or defaults to dev):
    DATABRICKS_HOST, DATABRICKS_PROFILE, CATALOG, SCHEMA, WAREHOUSE_ID
"""
import os
from databricks import sql
from databricks.sdk.core import Config

CATALOG = os.getenv("CATALOG", "morgan_stable_classic_6df0yw_catalog")
SCHEMA = os.getenv("SCHEMA", "doc_finder")
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/raw_docs"
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


def run():
    conn = get_connection()
    cursor = conn.cursor()

    print(f"Parsing PDFs from {VOLUME_PATH}...")
    cursor.execute(f"""
        CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.parsed_docs AS
        SELECT
            regexp_extract(path, '([^/]+$)', 1) AS filename,
            ai_parse_document(content, map('version', '2.0')):document::string AS parsed_text
        FROM READ_FILES('{VOLUME_PATH}/', format => 'binaryFile')
    """)

    cursor.execute(f"SELECT filename FROM {CATALOG}.{SCHEMA}.parsed_docs")
    rows = cursor.fetchall()
    print(f"Parsed {len(rows)} documents:")
    for row in rows:
        print(f"  - {row[0]}")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    run()
