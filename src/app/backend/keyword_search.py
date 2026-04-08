# backend/keyword_search.py
"""
SQL keyword search on extracted plain text.
Uses punctuation-normalized ILIKE for partial matching.
"""
import os
from databricks import sql
from databricks.sdk.core import Config

CATALOG = os.getenv("CATALOG", "morgan_stable_classic_6df0yw_catalog")
SCHEMA = os.getenv("SCHEMA", "doc_finder")
WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "")

# Characters to strip from both search term and plain_text before comparing
STRIP_CHARS = str.maketrans("", "", ":;- ")


def _normalize(term: str) -> str:
    """Strip punctuation/spaces for fuzzy substring matching."""
    return term.lower().translate(STRIP_CHARS)


def search_by_keyword(terms: list[str], max_results: int = 5) -> list[dict]:
    """
    Search document plain text for keyword matches.
    Normalizes punctuation so '45:28-33' matches '2006;45:28-33'.

    Returns list of dicts with keys: filename, summary, score, match_type
    """
    if not WAREHOUSE_ID or not terms:
        return []

    cfg = Config()
    conn = sql.connect(
        server_hostname=cfg.host.replace("https://", ""),
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: cfg.authenticate,
    )

    # Build OR conditions for each normalized term
    conditions = []
    for term in terms:
        safe = _normalize(term).replace("'", "''").replace("%", "\\%").replace("_", "\\_")
        conditions.append(
            f"REPLACE(REPLACE(REPLACE(REPLACE(LOWER(plain_text), ':', ''), ';', ''), '-', ''), ' ', '') "
            f"LIKE '%{safe}%'"
        )

    where_clause = " OR ".join(conditions)

    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT filename, summary
        FROM {CATALOG}.{SCHEMA}.doc_summaries
        WHERE {where_clause}
        LIMIT {max_results}
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {"filename": row[0], "summary": row[1], "score": 1.0, "match_type": "keyword"}
        for row in rows
    ]
