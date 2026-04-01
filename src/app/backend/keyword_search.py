# backend/keyword_search.py
"""
SQL keyword search on full document text.
Used for exact matches: SKUs, part numbers, regulatory codes, etc.
"""
import os
from databricks import sql
from databricks.sdk.core import Config

CATALOG = os.getenv("CATALOG", "morgan_stable_classic_6df0yw_catalog")
SCHEMA = os.getenv("SCHEMA", "doc_finder")
WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "")


def search_by_keyword(term: str, max_results: int = 5) -> list[dict]:
    """
    Search document full text for exact keyword matches.

    Returns list of dicts with keys: filename, summary, score
    """
    if not WAREHOUSE_ID:
        return []

    cfg = Config()
    conn = sql.connect(
        server_hostname=cfg.host.replace("https://", ""),
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: cfg.authenticate,
    )

    safe_term = term.replace("'", "''").replace("%", "\\%").replace("_", "\\_")

    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT filename, summary
        FROM {CATALOG}.{SCHEMA}.doc_summaries
        WHERE full_text ILIKE '%{safe_term}%'
        LIMIT {max_results}
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {"filename": row[0], "summary": row[1], "score": 1.0, "match_type": "keyword"}
        for row in rows
    ]
