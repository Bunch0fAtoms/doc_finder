#!/usr/bin/env python3
"""
Generate src/app/app.yaml from databricks.yml variables for a given target.
Optionally creates the UC schema/volume and uploads local PDFs.

Usage:
    python scripts/configure.py [target]
    python scripts/configure.py [target] --skip-upload

Examples:
    python scripts/configure.py          # Uses default target (dev)
    python scripts/configure.py dev      # Configure + upload PDFs
    python scripts/configure.py demo --skip-upload  # Skip PDF upload
"""
import subprocess
import json
import sys
import os
import glob

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

  - name: MLFLOW_APP_NAME
    value: "doc-finder-dev"
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


def get_workspace_profile(target=None):
    """Read the workspace profile from databricks bundle validate."""
    cmd = ["databricks", "bundle", "validate", "--output=json"]
    if target:
        cmd.extend(["-t", target])
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__)))
    if result.returncode != 0:
        return None
    data = json.loads(result.stdout)
    return data.get("workspace", {}).get("profile")


def ensure_schema_and_volume(variables, profile):
    """Create the UC schema and volume if they don't exist."""
    from databricks.sdk import WorkspaceClient

    catalog = variables["catalog"]
    schema = variables["schema"]
    volume = variables["volume_name"]

    w = WorkspaceClient(profile=profile)

    print(f"Ensuring schema {catalog}.{schema} exists...")
    try:
        w.schemas.create(name=schema, catalog_name=catalog, comment="Doc Finder")
        print(f"  Schema created.")
    except Exception as e:
        if "ALREADY_EXISTS" in str(e) or "already exists" in str(e).lower():
            print(f"  Schema already exists.")
        else:
            raise

    print(f"Ensuring volume {catalog}.{schema}.{volume} exists...")
    try:
        w.volumes.create(
            catalog_name=catalog, schema_name=schema, name=volume,
            volume_type="MANAGED", comment="Raw PDF documents for Doc Finder",
        )
        print(f"  Volume created.")
    except Exception as e:
        if "ALREADY_EXISTS" in str(e) or "already exists" in str(e).lower():
            print(f"  Volume already exists.")
        else:
            raise

    return w


def upload_pdfs(w, variables):
    """Upload local PDFs to the UC volume, skipping files that already exist."""
    catalog = variables["catalog"]
    schema = variables["schema"]
    volume = variables["volume_name"]
    volume_path = f"/Volumes/{catalog}/{schema}/{volume}"

    raw_docs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "raw_docs")
    pdf_files = [os.path.basename(f) for f in glob.glob(os.path.join(raw_docs_dir, "*.pdf"))]
    if not pdf_files:
        print(f"No PDFs found in {raw_docs_dir}")
        return

    # Check which files already exist
    existing = set()
    try:
        for entry in w.files.list_directory_contents(volume_path):
            if entry.name and entry.name.lower().endswith(".pdf"):
                existing.add(entry.name)
    except Exception:
        pass

    to_upload = [f for f in pdf_files if f not in existing]
    if not to_upload:
        print(f"All {len(pdf_files)} PDFs already exist in volume. Nothing to upload.")
        return

    print(f"Uploading {len(to_upload)} new PDFs to {volume_path}/ ({len(existing)} already exist)...")
    for filename in to_upload:
        local_path = os.path.join(raw_docs_dir, filename)
        remote_path = f"{volume_path}/{filename}"
        with open(local_path, "rb") as f:
            w.files.upload(remote_path, f, overwrite=True)
        print(f"  Uploaded {filename}")
    print("Upload complete.")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    skip_upload = "--skip-upload" in flags

    target = args[0] if args else None
    target_label = target or "default"
    print(f"Configuring for target: {target_label}")

    variables = get_bundle_variables(target)

    # 1. Generate app.yaml
    content = APP_YAML_TEMPLATE.format(**variables)
    output_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src", "app", "app.yaml")
    with open(output_path, "w") as f:
        f.write(content)

    print(f"Wrote {output_path}")
    print(f"  catalog:          {variables.get('catalog')}")
    print(f"  schema:           {variables.get('schema')}")
    print(f"  vs_endpoint:      {variables.get('vs_endpoint_name')}")
    print(f"  foundation_model: {variables.get('foundation_model')}")

    # 2. Create schema/volume and upload PDFs
    if skip_upload:
        print("\nSkipping PDF upload (--skip-upload).")
    else:
        print("\nSetting up schema, volume, and uploading PDFs...")
        profile = get_workspace_profile(target)
        w = ensure_schema_and_volume(variables, profile)
        upload_pdfs(w, variables)


if __name__ == "__main__":
    main()
