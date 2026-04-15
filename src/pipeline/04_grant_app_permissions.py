# src/pipeline/04_grant_app_permissions.py
"""
Grant the Databricks App service principal access to UC resources.

Runs locally after the app is created. The app SP ID is looked up
automatically from the app name.

Usage:
    python src/pipeline/04_grant_app_permissions.py \
        --catalog=morgancatalog --schema=doc_finder \
        --warehouse-id=4b9b953939869799 --volume=raw_docs \
        --app-name=doc-finder-Databricks_Demo
"""
from databricks import sql
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from _config import parse_config

cfg = parse_config("catalog", "schema", "warehouse_id", "volume", "app_name")
CATALOG = cfg["catalog"]
SCHEMA = cfg["schema"]
WAREHOUSE_ID = cfg["warehouse_id"]
VOLUME = cfg["volume"]
APP_NAME = cfg["app_name"]


def get_connection():
    sdk_cfg = Config()
    return sql.connect(
        server_hostname=sdk_cfg.host.replace("https://", ""),
        http_path=f"/sql/1.0/warehouses/{WAREHOUSE_ID}",
        credentials_provider=lambda: sdk_cfg.authenticate,
    )


def get_app_sp_id(app_name):
    """Look up the service principal client ID for a Databricks App."""
    w = WorkspaceClient()
    app = w.apps.get(app_name)
    sp_id = app.service_principal_client_id
    print(f"App '{app_name}' service principal: {sp_id}")
    return sp_id


def main():
    sp_id = get_app_sp_id(APP_NAME)

    conn = get_connection()
    cursor = conn.cursor()

    grants = [
        f"GRANT USE_CATALOG ON CATALOG {CATALOG} TO `{sp_id}`",
        f"GRANT USE_SCHEMA ON SCHEMA {CATALOG}.{SCHEMA} TO `{sp_id}`",
        f"GRANT SELECT ON TABLE {CATALOG}.{SCHEMA}.doc_summaries TO `{sp_id}`",
        f"GRANT SELECT ON TABLE {CATALOG}.{SCHEMA}.doc_summaries_index TO `{sp_id}`",
        f"GRANT READ_VOLUME ON VOLUME {CATALOG}.{SCHEMA}.{VOLUME} TO `{sp_id}`",
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
