#!/usr/bin/env python3
"""
Generate src/app/app.yaml from databricks.yml variables for a given target.

Usage:
    python scripts/configure.py [target]

Examples:
    python scripts/configure.py          # Uses default target (dev)
    python scripts/configure.py dev
    python scripts/configure.py prod
"""
import subprocess
import json
import sys
import os

APP_YAML_TEMPLATE = """command:
  - uvicorn
  - backend.main:app
  - --host
  - "0.0.0.0"
  - --port
  - "8000"

env:
  - name: DATABRICKS_WAREHOUSE_ID
    valueFrom: sql-warehouse

  - name: VS_ENDPOINT_NAME
    value: "{vs_endpoint_name}"

  - name: VS_INDEX_NAME
    value: "{vs_index_name}"

  - name: CATALOG
    value: "{catalog}"

  - name: SCHEMA
    value: "{schema}"

  - name: VOLUME
    value: "{volume_name}"

  - name: FOUNDATION_MODEL
    value: "{foundation_model}"

  - name: MLFLOW_EXPERIMENT
    value: "/Shared/doc-finder"

  - name: APP_VERSION
    value: "{app_version}"
"""


def get_bundle_variables(target=None):
    """Read resolved variables from databricks bundle validate."""
    cmd = ["databricks", "bundle", "validate", "--output=json"]
    if target:
        cmd.extend(["-t", target])
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)))
    if result.returncode != 0:
        print(f"Error validating bundle: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(result.stdout)
    return {k: v.get("value", v.get("default", "")) for k, v in data.get("variables", {}).items()}


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    target_label = target or "default"
    print(f"Configuring app.yaml for target: {target_label}")

    variables = get_bundle_variables(target)

    # Build app version: bundle-name/branch@commit
    try:
        repo_dir = os.path.dirname(os.path.dirname(__file__))
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=repo_dir
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=repo_dir
        ).stdout.strip()
        bundle_name = "doc-finder"
        variables["app_version"] = f"{bundle_name}/{branch}@{commit}" if commit else "dev"
    except Exception:
        variables["app_version"] = "dev"

    content = APP_YAML_TEMPLATE.format(**variables)

    output_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src", "app", "app.yaml")
    with open(output_path, "w") as f:
        f.write(content)

    print(f"Wrote {output_path}")
    print(f"  catalog:          {variables.get('catalog')}")
    print(f"  schema:           {variables.get('schema')}")
    print(f"  vs_endpoint:      {variables.get('vs_endpoint_name')}")
    print(f"  foundation_model: {variables.get('foundation_model')}")


if __name__ == "__main__":
    main()
