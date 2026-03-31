# pipeline/04_grant_app_permissions.py
"""
Grant the Databricks App service principal access to UC resources.
Run this after creating the app and before using it.

Configuration via environment variables (or defaults to dev):
    DATABRICKS_HOST, DATABRICKS_PROFILE, CATALOG, SCHEMA, WAREHOUSE_ID, APP_SP_ID

To find the APP_SP_ID, run:
    databricks apps get <app-name> --output=json | jq .service_principal_client_id
"""
import os
from databricks import sql
from databricks.sdk.core import Config

CATALOG = os.getenv("CATALOG", "morgan_stable_classic_6df0yw_catalog")
SCHEMA = os.getenv("SCHEMA", "doc_finder")
WAREHOUSE_ID = os.getenv("WAREHOUSE_ID", "718f1b203cdea5c4")
APP_SP_ID = os.getenv("APP_SP_ID", "d99bfa3d-807d-4d69-b581-77c8b65c6235")


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
