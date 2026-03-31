# src/pipeline/01_parse_docs.py
"""
Parse PDFs from Unity Catalog volume using ai_parse_document.

DABs:  databricks bundle run data_pipeline (runs all 3 steps)
Local: python src/pipeline/01_parse_docs.py --catalog=X --schema=X --warehouse-id=X
"""
from databricks import sql
from databricks.sdk.core import Config
from _config import parse_config

cfg = parse_config("catalog", "schema", "warehouse_id", "volume")
CATALOG = cfg["catalog"]
SCHEMA = cfg["schema"]
WAREHOUSE_ID = cfg["warehouse_id"]
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{cfg['volume']}"


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

    print(f"Parsing PDFs from {VOLUME_PATH}...")
    print(f"Writing to {CATALOG}.{SCHEMA}.parsed_docs")
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
    main()
