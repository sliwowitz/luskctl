# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Task display types and status computation.

Provides display-oriented dataclasses (``StatusInfo``, ``ModeInfo``),
status/mode lookup tables, and functions for computing the effective
status and mode emoji of a task.

Split from ``tasks.py`` to decouple presentation data from task
lifecycle and metadata I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tasks import TaskMeta


@dataclass(frozen=True)
class StatusInfo:
    """Display attributes for a task effective status."""

    label: str
    emoji: str
    color: str


@dataclass(frozen=True)
class ModeInfo:
    """Display attributes for a task mode."""

    emoji: str
    label: str


STATUS_DISPLAY: dict[str, StatusInfo] = {
    "running": StatusInfo(label="running", emoji="🟢", color="green"),
    "stopped": StatusInfo(label="stopped", emoji="🟡", color="yellow"),
    "completed": StatusInfo(label="completed", emoji="✅", color="green"),
    "failed": StatusInfo(label="failed", emoji="❌", color="red"),
    "created": StatusInfo(label="created", emoji="🆕", color="yellow"),
    "not found": StatusInfo(label="not found", emoji="❓", color="yellow"),
    "deleting": StatusInfo(label="deleting", emoji="🧹", color="yellow"),
}

MODE_DISPLAY: dict[str | None, ModeInfo] = {
    "cli": ModeInfo(emoji="💻", label="CLI"),
    "web": ModeInfo(emoji="🌍", label="Web"),
    "run": ModeInfo(emoji="🚀", label="Autopilot"),
    None: ModeInfo(emoji="🦗", label=""),
}

WEB_BACKEND_EMOJI: dict[str, str] = {
    "claude": "💠",
    "codex": "🌸",
    "mistral": "🏰",
    "copilot": "🤖",
}

WEB_BACKEND_DEFAULT_EMOJI = "🌍"


def effective_status(task: TaskMeta) -> str:
    """Compute the display status from task metadata + live container state.

    Reads the following fields from a ``TaskMeta`` instance:

    - ``container_state`` (str | None): live podman state, or None
    - ``mode`` (str | None): task mode (cli/web/run/None)
    - ``exit_code`` (int | None): process exit code, or None
    - ``deleting`` (bool): persisted to YAML before deletion starts

    Returns one of: ``"deleting"``, ``"running"``, ``"stopped"``,
    ``"completed"``, ``"failed"``, ``"created"``, ``"not found"``.
    """
    if task.deleting:
        return "deleting"

    cs = task.container_state
    mode = task.mode
    exit_code = task.exit_code

    if cs == "running":
        return "running"

    if cs is not None:
        # Container exists but is not running
        if exit_code is not None and exit_code == 0:
            return "completed"
        if exit_code is not None and exit_code != 0:
            return "failed"
        return "stopped"

    # No container found
    if mode is None:
        return "created"
    if exit_code is not None and exit_code == 0:
        return "completed"
    if exit_code is not None and exit_code != 0:
        return "failed"
    return "not found"


def mode_emoji(task: TaskMeta) -> str:
    """Return the mode emoji for a task, resolving web backends.

    For ``mode="web"``, the emoji is looked up from ``WEB_BACKEND_EMOJI``
    using the task's ``backend`` field.  Other modes use ``MODE_DISPLAY``.
    """
    mode = task.mode
    if mode == "web":
        backend = task.backend
        if isinstance(backend, str):
            return WEB_BACKEND_EMOJI.get(backend, WEB_BACKEND_DEFAULT_EMOJI)
        return WEB_BACKEND_DEFAULT_EMOJI
    info = MODE_DISPLAY.get(mode if isinstance(mode, str) else None)
    return info.emoji if info else MODE_DISPLAY[None].emoji
