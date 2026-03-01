# SPDX-FileCopyrightText: 2025-2026 Jiri Vyskocil <jiri@vyskocil.com>
#
# SPDX-License-Identifier: Apache-2.0

"""Agent instruction resolution: layered merging with bundled defaults.

Resolves the ``instructions`` config key from the merged agent-config dict,
supporting flat strings, per-provider dicts, and lists with ``_inherit``
concatenation.  Falls back to a bundled default that describes the standard
luskctl container environment.
"""

from __future__ import annotations

import importlib.resources
from typing import Any


def bundled_default_instructions() -> str:
    """Read and return the bundled default instructions from package resources."""
    ref = importlib.resources.files("luskctl.resources.instructions").joinpath("default.md")
    return ref.read_text(encoding="utf-8")


def resolve_instructions(config: dict[str, Any], provider_name: str) -> str:
    """Resolve instructions from a merged config dict.

    Supports:
    - Flat string: returned as-is
    - Per-provider dict: uses :func:`resolve_provider_value`, falls back to ``_default``
    - List (with optional ``_inherit``): already merged by ConfigStack, joined with ``\\n\\n``
    - Absent/None: returns bundled default

    Returns the final instructions text.
    """
    from .agent_config import resolve_provider_value

    val = config.get("instructions")

    if val is None:
        return bundled_default_instructions()

    # Per-provider dict (e.g. {claude: "...", codex: "...", _default: "..."})
    if isinstance(val, dict):
        resolved = resolve_provider_value("instructions", config, provider_name)
        if resolved is None:
            return bundled_default_instructions()
        if isinstance(resolved, list):
            return "\n\n".join(str(item) for item in resolved if item != "_inherit")
        return str(resolved)

    # List form (already merged by ConfigStack via _inherit splicing)
    if isinstance(val, list):
        return "\n\n".join(str(item) for item in val if item != "_inherit")

    # Flat string
    return str(val)


def has_custom_instructions(config: dict[str, Any]) -> bool:
    """Check if config has explicit (non-default) instructions."""
    return config.get("instructions") is not None
