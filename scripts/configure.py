#!/usr/bin/env python3
"""
Generate src/app/app.yaml from databricks.yml variables for a given target.

Works both locally and in the Databricks workspace editor.
No external dependencies — parses databricks.yml with PyYAML if available,
falls back to a simple parser for the variables/targets sections.

Usage (local):      python scripts/configure.py demo
Usage (workspace):  Run as Python file, click "Add parameter" and enter: demo
                    (the Target dropdown in the sidebar is for DABs deploy, not this script)
"""
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

  - name: MLFLOW_APP_NAME
    value: "doc-finder-dev"
"""


def _find_project_root():
    """Find the project root by locating databricks.yml."""
    # Try relative to this script (works locally)
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidate = os.path.dirname(script_dir)
        if os.path.isfile(os.path.join(candidate, "databricks.yml")):
            return candidate
    except NameError:
        pass

    # Try CWD
    if os.path.isfile(os.path.join(os.getcwd(), "databricks.yml")):
        return os.getcwd()

    # Search up from CWD
    path = os.getcwd()
    for _ in range(10):
        if os.path.isfile(os.path.join(path, "databricks.yml")):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent

    raise FileNotFoundError("Cannot find databricks.yml. Run from the project directory.")


def _load_yaml(path):
    """Load YAML file, using PyYAML if available, otherwise a simple parser."""
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f)
    except ImportError:
        pass

    # Simple fallback parser for our databricks.yml structure
    with open(path) as f:
        text = f.read()

    # Use the built-in json module to parse after converting simple YAML to dict
    # This handles our specific databricks.yml format
    import re
    result = {"variables": {}, "targets": {}}

    # Extract variable defaults
    in_variables = False
    current_var = None
    in_targets = False
    current_target = None
    in_target_vars = False

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Top-level sections
        if line.startswith("variables:"):
            in_variables = True
            in_targets = False
            continue
        if line.startswith("targets:"):
            in_targets = True
            in_variables = False
            continue
        if not line.startswith(" ") and not line.startswith("\t"):
            in_variables = False
            in_targets = False
            continue

        if in_variables:
            # Variable name (2-space indent)
            m = re.match(r"^  (\w+):", line)
            if m:
                current_var = m.group(1)
                result["variables"][current_var] = {}
                continue
            # Variable properties (4-space indent)
            if current_var:
                m = re.match(r'^    default:\s*"?([^"]*)"?', line)
                if m:
                    result["variables"][current_var]["default"] = m.group(1).strip()

        if in_targets:
            # Target name (2-space indent)
            m = re.match(r"^  (\w[\w-]*):", line)
            if m and not stripped.startswith("variables:"):
                current_target = m.group(1)
                result["targets"][current_target] = {"variables": {}}
                in_target_vars = False
                continue
            if current_target:
                if stripped == "variables:":
                    in_target_vars = True
                    continue
                if in_target_vars:
                    m = re.match(r'^\s+(\w+):\s*"?([^"]*)"?', line)
                    if m:
                        result["targets"][current_target]["variables"][m.group(1)] = m.group(2).strip()

    return result


def get_bundle_variables(project_root, target=None):
    """Read variables from databricks.yml, resolving target overrides."""
    bundle_path = os.path.join(project_root, "databricks.yml")
    bundle = _load_yaml(bundle_path)

    # Start with defaults
    variables = {}
    for k, v in bundle.get("variables", {}).items():
        if isinstance(v, dict):
            variables[k] = v.get("default", "")
        else:
            variables[k] = str(v)

    # Apply target overrides
    if target:
        targets = bundle.get("targets", {})
        if target not in targets:
            print(f"Warning: target '{target}' not found in databricks.yml")
        else:
            target_vars = targets[target].get("variables", {})
            variables.update(target_vars)

    return variables


def main():
    # Parse target from args.
    # Workspace editor injects extra args like: -f /databricks/kernel-connections/...json
    # Support both positional (local) and --target=X (explicit) forms.
    target = None

    # Check for explicit --target=X first
    for arg in sys.argv[1:]:
        if arg.startswith("--target="):
            target = arg.split("=", 1)[1]
            break

    # Fall back to positional args, but only accept simple names (no paths or flags)
    if target is None:
        for arg in sys.argv[1:]:
            if not arg.startswith("-") and "/" not in arg and "." not in arg:
                target = arg
                break

    target_label = target or "default"
    print(f"Configuring app.yaml for target: {target_label}")

    project_root = _find_project_root()
    variables = get_bundle_variables(project_root, target)
    content = APP_YAML_TEMPLATE.format(**variables)

    output_path = os.path.join(project_root, "src", "app", "app.yaml")
    with open(output_path, "w") as f:
        f.write(content)

    print(f"Wrote {output_path}")
    print(f"  catalog:          {variables.get('catalog')}")
    print(f"  schema:           {variables.get('schema')}")
    print(f"  vs_endpoint:      {variables.get('vs_endpoint_name')}")
    print(f"  foundation_model: {variables.get('foundation_model')}")


if __name__ == "__main__":
    main()
