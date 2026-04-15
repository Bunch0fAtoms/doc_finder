#!/usr/bin/env python3
"""
Generate src/app/app.yaml from databricks.yml variables for a given target.

Works both locally and in the Databricks workspace editor.
No external dependencies — parses databricks.yml with PyYAML if available,
falls back to a simple parser for the variables/targets sections.

MLFLOW_APP_NAME is derived from the current git branch (sanitized). If git is unavailable,
it falls back to doc-finder-<target> to match bundle app naming.

DATABRICKS_APP_NAME must match the deployed app name from the bundle (doc-finder-<target>)
and is used for Workspace Apps API lookups — not the branch label.

Usage (local):
  python scripts/configure.py Databricks_Demo
  python scripts/configure.py --target=Databricks_Demo
  python scripts/configure.py --target Databricks_Demo
  BUNDLE_TARGET=Databricks_Demo python scripts/configure.py

Workspace / notebook runs often only pass ``-f /path/to/kernel.json`` — set the target explicitly:
  --target=Databricks_Demo as an argument, or environment variable BUNDLE_TARGET (or DATABRICKS_BUNDLE_TARGET).
If no target is given, resolution order is: environment variables → git branch name if it matches a
target → Databricks CLI local cache ``~/.bundle/<bundle>/<target>``
(most recently used target) → bundle ``default: true`` in databricks.yml.

``databricks bundle deploy -t Databricks_Demo`` does not set env vars for ``configure.py``; use ``--target``,
``BUNDLE_TARGET``, matching git branch name, or rely on ``~/.bundle/...`` after a prior deploy.
"""
import os
import re
import subprocess
import sys
from typing import List, Optional, Tuple

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

  - name: CLASSIFIER_MODEL
    value: "{classifier_model}"

  - name: MLFLOW_EXPERIMENT
    value: "/Shared/doc-finder"

  - name: DATABRICKS_APP_NAME
    value: "{databricks_app_name}"

  - name: MLFLOW_APP_NAME
    value: "{mlflow_app_name}"
"""


def _git_branch(project_root: str) -> Optional[str]:
    """Return current git branch name, or None if not a git repo / git missing."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        b = out.stdout.strip()
        return b if b else None
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def _sanitize_branch_for_name(branch: str) -> str:
    """Make branch string safe for MLflow LoggedModel / env value (alnum + hyphen)."""
    s = branch.strip().lower().replace("/", "-")
    s = re.sub(r"[^a-z0-9._-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "unknown"


def _compute_app_names(project_root: str, target: Optional[str]) -> Tuple[str, str]:
    """
    Returns (databricks_app_name, mlflow_app_name).

    databricks_app_name: must match bundle resources.apps.*.name = doc-finder-<target>.
    mlflow_app_name: doc-finder-<sanitized-git-branch>, or doc-finder-<target> if no git.

    If ``target`` is missing, uses the bundle default from databricks.yml (``default: true``),
    never a hardcoded name like ``dev``.
    """
    t = target if target else _default_bundle_target(project_root)
    databricks_app_name = f"doc-finder-{t}"

    branch = _git_branch(project_root)
    if branch:
        mlflow_app_name = f"doc-finder-{_sanitize_branch_for_name(branch)}"
    else:
        mlflow_app_name = databricks_app_name

    return databricks_app_name, mlflow_app_name


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
                # Parse host from workspace section
                m_host = re.match(r'^\s+host:\s*"?([^"]*)"?', line)
                if m_host and not in_target_vars:
                    result["targets"][current_target]["host"] = m_host.group(1).strip().rstrip("/")
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


def _bundle_target_names(project_root: str) -> List[str]:
    bundle_path = os.path.join(project_root, "databricks.yml")
    bundle = _load_yaml(bundle_path)
    return list(bundle.get("targets", {}).keys())


def _default_bundle_target(project_root: str) -> str:
    bundle_path = os.path.join(project_root, "databricks.yml")
    bundle = _load_yaml(bundle_path)
    for name, cfg in bundle.get("targets", {}).items():
        if isinstance(cfg, dict) and cfg.get("default"):
            return name
    names = list(bundle.get("targets", {}).keys())
    return names[0] if names else "dev"


def _bundle_name(project_root: str) -> str:
    """Bundle name from databricks.yml (``bundle.name``), default doc-finder."""
    path = os.path.join(project_root, "databricks.yml")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        m = re.search(r"^bundle:\s*\n\s*name:\s*([^\s#]+)", text, re.MULTILINE)
        if m:
            return m.group(1).strip().strip("\"'")
    except OSError:
        pass
    data = _load_yaml(path)
    b = data.get("bundle") if isinstance(data, dict) else None
    if isinstance(b, dict) and b.get("name"):
        return str(b["name"]).strip()
    return "doc-finder"


def _infer_target_from_git_branch(project_root: str, known: set) -> Tuple[Optional[str], str]:
    """If current git branch name equals a bundle target (e.g. demo, dev), use it."""
    branch = _git_branch(project_root)
    if branch and branch in known:
        return (branch, "git branch (matches target name)")
    return (None, "")


def _infer_target_from_bundle_cache(project_root: str, known: set) -> Tuple[Optional[str], str]:
    """
    Databricks CLI stores per-target state under ~/.bundle/<bundle-name>/<target>/.
    Pick the known target directory with the most recent mtime (last deploy / bundle use).
    """
    bname = _bundle_name(project_root)
    root = os.path.expanduser(os.path.join("~", ".bundle", bname))
    if not os.path.isdir(root):
        return (None, "")
    best: Optional[str] = None
    best_mtime = -1.0
    for name in os.listdir(root):
        if name not in known:
            continue
        p = os.path.join(root, name)
        if not os.path.isdir(p):
            continue
        try:
            mtime = os.path.getmtime(p)
        except OSError:
            continue
        if mtime > best_mtime:
            best_mtime = mtime
            best = name
    if best:
        return (best, f"~/.bundle/{bname}/<target> (most recent)")
    return (None, "")


def _parse_target(project_root: str) -> Tuple[Optional[str], str]:
    """
    Resolve bundle target. Not implicitly equal to ``databricks bundle deploy -t`` unless
    env / cache / git branch provides it — see module docstring.
    """
    known = set(_bundle_target_names(project_root))
    argv = sys.argv[1:]

    for a in argv:
        if a.startswith("--target="):
            v = a.split("=", 1)[1].strip()
            return (v, "explicit --target=...")

    for i, a in enumerate(argv):
        if a == "--target" and i + 1 < len(argv):
            return (argv[i + 1].strip(), "explicit --target <name>")

    # Strip -f /path pairs (Databricks / Jupyter)
    filtered: List[str] = []
    i = 0
    while i < len(argv):
        if argv[i] in ("-f", "--file") and i + 1 < len(argv):
            i += 2
            continue
        filtered.append(argv[i])
        i += 1

    for a in filtered:
        if a.startswith("-"):
            continue
        if a in known:
            return (a, "argv")

    for key in (
        "BUNDLE_TARGET",
        "DATABRICKS_BUNDLE_TARGET",
        "DATABRICKS_CLI_BUNDLE_TARGET",
    ):
        v = os.environ.get(key, "").strip()
        if v:
            return (v, key)

    t, src = _infer_target_from_git_branch(project_root, known)
    if t:
        return (t, src)

    t, src = _infer_target_from_bundle_cache(project_root, known)
    if t:
        return (t, src)

    return (None, "")


def main():
    project_root = _find_project_root()
    target, target_src = _parse_target(project_root)
    if not target:
        target = _default_bundle_target(project_root)
        target_src = "bundle default (databricks.yml: default: true)"

    print(f"Configuring app.yaml for target: {target}  [{target_src}]")
    variables = get_bundle_variables(project_root, target)
    databricks_app_name, mlflow_app_name = _compute_app_names(project_root, target)
    variables = {
        **variables,
        "databricks_app_name": databricks_app_name,
        "mlflow_app_name": mlflow_app_name,
    }
    content = APP_YAML_TEMPLATE.format(**variables)

    output_path = os.path.join(project_root, "src", "app", "app.yaml")
    with open(output_path, "w") as f:
        f.write(content)

    print(f"Wrote {output_path}")
    print(f"  catalog:          {variables.get('catalog')}")
    print(f"  schema:           {variables.get('schema')}")
    print(f"  vs_endpoint:      {variables.get('vs_endpoint_name')}")
    print(f"  foundation_model: {variables.get('foundation_model')}")
    print(f"  databricks_app:   {databricks_app_name}")
    print(f"  mlflow_app:       {mlflow_app_name}  (from git branch if available)")


if __name__ == "__main__":
    main()
