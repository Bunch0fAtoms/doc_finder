# src/pipeline/_config.py
"""
Shared config parser for pipeline scripts.
Reads from CLI args (--key=value, injected by DABs) with fallback to env vars.
"""
import os
import sys


def parse_config(*keys: str) -> dict[str, str]:
    """
    Parse config values from CLI args or environment variables.

    DABs jobs pass --key=value args. Local runs use env vars.

    Usage:
        cfg = parse_config("catalog", "schema", "warehouse_id")
        print(cfg["catalog"])
    """
    config = {}

    # Parse --key=value args
    arg_map = {}
    for arg in sys.argv[1:]:
        if arg.startswith("--") and "=" in arg:
            k, v = arg[2:].split("=", 1)
            arg_map[k.replace("-", "_")] = v

    for key in keys:
        cli_key = key.lower().replace("-", "_")
        env_key = key.upper().replace("-", "_")
        value = arg_map.get(cli_key) or os.environ.get(env_key)
        if not value:
            print(f"Error: {env_key} not set. Pass --{cli_key.replace('_', '-')}=VALUE or set {env_key} env var.")
            sys.exit(1)
        config[cli_key] = value

    return config
