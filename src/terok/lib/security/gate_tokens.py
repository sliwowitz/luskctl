# SPDX-FileCopyrightText: 2025-2026 Jiri Vyskocil <jiri@vyskocil.com>
#
# SPDX-License-Identifier: Apache-2.0

"""Token CRUD for gate server per-task authentication.

Each task gets a random 128-bit hex token scoped to its project.  Tokens are
stored in ``state_root()/gate/tokens.json`` and read by the standalone gate
server process (which receives the file path via ``--token-file``).

File format::

    {"<token_hex>": {"project": "<project_id>", "task": "<task_id>"}}
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import tempfile
from pathlib import Path

from ..core.config import state_root


def token_file_path() -> Path:
    """Return the path to the shared token file."""
    return state_root() / "gate" / "tokens.json"


def create_token(project_id: str, task_id: str) -> str:
    """Generate a 128-bit hex token, persist atomically, and return it.

    Uses ``secrets.token_hex(16)`` for cryptographic randomness.
    Atomic write via ``tempfile`` + ``os.replace()``.
    """
    token = secrets.token_hex(16)
    path = token_file_path()
    tokens = _read_tokens(path)
    tokens[token] = {"project": project_id, "task": task_id}
    _write_tokens(path, tokens)
    return token


def revoke_token_for_task(project_id: str, task_id: str) -> None:
    """Remove all tokens for the given project+task pair.  Idempotent."""
    path = token_file_path()
    tokens = _read_tokens(path)
    to_remove = [
        t
        for t, info in tokens.items()
        if info.get("project") == project_id and info.get("task") == task_id
    ]
    if not to_remove:
        return
    for t in to_remove:
        del tokens[t]
    _write_tokens(path, tokens)


def _read_tokens(path: Path) -> dict[str, dict[str, str]]:
    """Load tokens.json.  Returns ``{}`` on missing or corrupt file."""
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_tokens(path: Path, tokens: dict) -> None:
    """Atomic write: write to a temp file, then ``os.replace()`` over the original."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(tokens, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
