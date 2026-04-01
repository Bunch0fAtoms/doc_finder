# src/pipeline/04_grant_app_permissions.py
"""
Grant the Databricks App service principal access to UC resources.
Runs as a DABs job or locally. All config from environment variables.

APP_SP_ID must be set after app creation:
    databricks apps get <app-name> --output=json | jq .service_principal_client_id
"""
import os
from databricks import sql
from databricks.sdk.core import Config

CATALOG = os.environ["CATALOG"]
SCHEMA = os.environ["SCHEMA"]
WAREHOUSE_ID = os.environ["WAREHOUSE_ID"]
APP_SP_ID = os.environ["APP_SP_ID"]


def get_connection():
    cfg = Config()
    return sql.connect(
        server_hostname=cfg.host.replace("https://", ""),
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: cfg.authenticate,
    )


def main():
    conn = get_connection()
    cursor = conn.cursor()

    grants = [
        f"GRANT USE_CATALOG ON CATALOG {CATALOG} TO `{APP_SP_ID}`",
        f"GRANT USE_SCHEMA ON SCHEMA {CATALOG}.{SCHEMA} TO `{APP_SP_ID}`",
        f"GRANT SELECT ON TABLE {CATALOG}.{SCHEMA}.doc_summaries_index TO `{APP_SP_ID}`",
        f"GRANT SELECT ON TABLE {CATALOG}.{SCHEMA}.doc_summaries TO `{APP_SP_ID}`",
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
    main()
