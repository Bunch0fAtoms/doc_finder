# src/pipeline/00_upload_docs.py
"""
Create UC schema/volume and upload PDFs to the Unity Catalog volume.

Reads PDFs from the workspace path where DABs deploys the raw_docs/ folder.
Skips files that already exist in the volume.

Pass --skip-upload=true to skip the PDF upload (e.g. when using your own
pipeline to land PDFs). Schema and volume are always created.

DABs:  databricks bundle run data_pipeline (runs as first step)
"""
import os
import io
import sys
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import VolumeType
from _config import parse_config

cfg = parse_config("catalog", "schema", "volume")
CATALOG = cfg["catalog"]
SCHEMA = cfg["schema"]
VOLUME = cfg["volume"]
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"


def _parse_flag(name, default=""):
    """Parse a --flag=value from sys.argv or env var."""
    env_key = name.upper().replace("-", "_")
    for arg in sys.argv[1:]:
        if arg.startswith(f"--{name}="):
            return arg.split("=", 1)[1]
    return os.environ.get(env_key, default)


def _find_raw_docs_workspace_path():
    """
    Determine the workspace path to raw_docs/.

    When running as a DABs serverless task, CWD is the bundle's file_path root.
    raw_docs/ is at the top level of the bundle.
    """
    # Try CWD first (DABs serverless sets CWD to bundle root)
    cwd_path = os.path.join(os.getcwd(), "raw_docs")
    if os.path.isdir(cwd_path):
        return cwd_path, "local"

    # Try relative to this script (src/pipeline/ -> ../../raw_docs/)
    try:
        script_relative = os.path.join(os.path.dirname(__file__), "..", "..", "raw_docs")
        script_relative = os.path.normpath(script_relative)
        if os.path.isdir(script_relative):
            return script_relative, "local"
    except NameError:
        pass  # __file__ not defined in workspace exec() context

    # Try known workspace paths (DABs source-linked deployment)
    # The script runs from /Workspace/Users/.../doc_finder/src/pipeline/
    # raw_docs is at /Workspace/Users/.../doc_finder/raw_docs/
    for arg in sys.argv:
        if "/Workspace/" in arg and "00_upload_docs" in arg:
            # Extract project root from the script path
            parts = arg.split("/src/pipeline/")[0]
            candidate = os.path.join(parts, "raw_docs")
            if os.path.isdir(candidate):
                return candidate, "local"

    # Search up from CWD
    path = os.getcwd()
    for _ in range(5):
        candidate = os.path.join(path, "raw_docs")
        if os.path.isdir(candidate):
            return candidate, "local"
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent

    return None, None


def main():
    w = WorkspaceClient()

    # Always ensure schema exists
    print(f"Ensuring schema {CATALOG}.{SCHEMA} exists...")
    try:
        w.schemas.create(name=SCHEMA, catalog_name=CATALOG, comment="Doc Finder")
        print("  Schema created.")
    except Exception as e:
        if "ALREADY_EXISTS" in str(e) or "already exists" in str(e).lower():
            print("  Schema already exists.")
        else:
            raise

    # Always ensure volume exists
    print(f"Ensuring volume {CATALOG}.{SCHEMA}.{VOLUME} exists...")
    try:
        w.volumes.create(
            catalog_name=CATALOG, schema_name=SCHEMA, name=VOLUME,
            volume_type=VolumeType.MANAGED, comment="Raw PDF documents for Doc Finder",
        )
        print("  Volume created.")
    except Exception as e:
        if "ALREADY_EXISTS" in str(e) or "already exists" in str(e).lower():
            print("  Volume already exists.")
        else:
            raise

    # Check skip toggle
    skip = _parse_flag("skip-upload", "false").lower() in ("true", "1", "yes")
    if skip:
        print("PDF upload skipped (--skip-upload=true).")
        return

    # Find raw_docs
    source_dir, source_type = _find_raw_docs_workspace_path()
    if source_dir is None:
        print("Could not find raw_docs/ directory. Skipping PDF upload.")
        print("  Make sure raw_docs/ is at the bundle root and included in the sync.")
        return

    # List local PDFs
    pdf_files = [f for f in os.listdir(source_dir) if f.lower().endswith(".pdf")]
    if not pdf_files:
        print(f"No PDFs found in {source_dir}")
        return

    # Check which files already exist in the volume
    existing = set()
    try:
        for entry in w.files.list_directory_contents(VOLUME_PATH):
            if entry.name and entry.name.lower().endswith(".pdf"):
                existing.add(entry.name)
    except Exception:
        pass

    to_upload = [f for f in pdf_files if f not in existing]
    if not to_upload:
        print(f"All {len(pdf_files)} PDFs already exist in volume. Nothing to upload.")
        return

    print(f"Uploading {len(to_upload)} new PDFs to {VOLUME_PATH}/ ({len(existing)} already exist)...")
    for filename in to_upload:
        local_path = os.path.join(source_dir, filename)
        remote_path = f"{VOLUME_PATH}/{filename}"
        with open(local_path, "rb") as f:
            w.files.upload(remote_path, f, overwrite=True)
        print(f"  Uploaded {filename}")

    print("Upload complete.")


if __name__ == "__main__":
    main()
