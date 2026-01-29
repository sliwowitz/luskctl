#!/usr/bin/env python3
"""
Shared functionality for OpenCode-based agents (blablador, opencode-custom, etc.).

This module provides common functions for OpenCode configuration and execution
to minimize code duplication between different OpenCode-based agents.
"""

import json
import subprocess
from pathlib import Path


def _opencode_config_path() -> Path:
    """Return the standard OpenCode config path."""
    return Path.home() / ".config" / "opencode" / "opencode.json"


def _load_opencode_config() -> dict | None:
    """Load existing OpenCode config if present."""
    config_path = _opencode_config_path()
    if not config_path.is_file():
        return None
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_opencode_config(config: dict) -> Path:
    """Write config to OpenCode's standard location."""
    config_path = _opencode_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


def _ensure_full_permissions(config: dict) -> dict:
    """Ensure the config has full permissions (like blablador)."""
    if "permission" not in config:
        config["permission"] = {"*": "allow"}
    return config


def run_opencode() -> int:
    """Run OpenCode CLI."""
    try:
        return subprocess.call(["opencode"])
    except FileNotFoundError:
        raise SystemExit("opencode not found. Rebuild the L1 CLI image to install it.")
