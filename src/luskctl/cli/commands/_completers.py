"""Shared argcomplete completers for CLI commands."""

from __future__ import annotations

import argparse

from ...lib.core.projects import list_projects


def complete_project_ids(
    prefix: str, parsed_args: argparse.Namespace, **kwargs: object
) -> list[str]:  # pragma: no cover
    """Return project IDs matching *prefix* for argcomplete."""
    try:
        ids = [p.id for p in list_projects()]
    except Exception:
        return []
    if prefix:
        ids = [i for i in ids if str(i).startswith(prefix)]
    return ids
