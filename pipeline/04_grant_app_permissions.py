# pipeline/04_grant_app_permissions.py
"""
Grant the Databricks App service principal access to UC resources.
Run this after creating the app and before using it.

The app's service principal needs:
- USE_CATALOG on the catalog
- USE_SCHEMA on the schema
- SELECT on the vector search index
- READ_VOLUME on the raw_docs volume
"""
from databricks import sql
from databricks.sdk.core import Config

CATALOG = "morgan_stable_classic_6df0yw_catalog"
SCHEMA = "doc_finder"
WAREHOUSE_ID = "718f1b203cdea5c4"

# App service principal application ID (from `databricks apps get doc-finder`)
APP_SP_ID = "d99bfa3d-807d-4d69-b581-77c8b65c6235"


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


def run():
    conn = get_connection()
    cursor = conn.cursor()

    grants = [
        f"GRANT USE_CATALOG ON CATALOG {CATALOG} TO `{APP_SP_ID}`",
        f"GRANT USE_SCHEMA ON SCHEMA {CATALOG}.{SCHEMA} TO `{APP_SP_ID}`",
        f"GRANT SELECT ON TABLE {CATALOG}.{SCHEMA}.doc_summaries_index TO `{APP_SP_ID}`",
        f"GRANT READ_VOLUME ON VOLUME {CATALOG}.{SCHEMA}.raw_docs TO `{APP_SP_ID}`",
    ]

    for grant_sql in grants:
        print(f"Running: {grant_sql}")
        cursor.execute(grant_sql)
        print("  Done.")

    cursor.close()
    conn.close()
    print("\nAll permissions granted.")


if __name__ == "__main__":
    run()
