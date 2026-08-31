# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Persist build/run output — terok glue over the terok-util capture facility.

The capture mechanism (pty tee, journald/file sinks) lives in
[`terok_util.output_capture`][terok_util.output_capture]; this module adds
only the terok-specific bits: the ``TEROK_KIND``/``PROJECT``/``TASK``
journald fields and the file-fallback path under
[`core_state_dir`][terok.lib.core.paths.core_state_dir].  The CLI command
handlers wrap an operation with [`tee_output`][terok.lib.util.output_capture.tee_output];
everything below the seam is shared with the rest of the fleet.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from terok_util import tee_output as _util_tee_output

_IDENTIFIER = "terok"
"""``SYSLOG_IDENTIFIER`` for captured build/run output in journald."""


def _reject_unsafe_component(value: str, label: str) -> None:
    """Raise ``ValueError`` if *value* cannot be a single path component safely.

    ``project``, ``kind`` and ``task_id`` all land in the fallback log path —
    ``project`` as a directory level under
    [`core_state_dir`][terok.lib.core.paths.core_state_dir], ``kind``/``task_id``
    interpolated into the filename.  A value carrying a NUL, a path separator,
    or a bare ``.``/``..`` could escape that tree — ``task_id="../../etc/cron.d/x"``
    or an absolute ``"/etc/passwd"`` would otherwise resolve a log path outside
    the state dir.  Traversal is a bug or an attack, never a real component, so
    every one of the three fails loud here rather than being silently rewritten.
    """
    separators = {"/", os.sep} | ({os.altsep} if os.altsep else set())
    if "\0" in value or separators & set(value) or value in (os.curdir, os.pardir):
        raise ValueError(f"unsafe {label} for log path: {value!r}")


def _logs_dir(project: str | None) -> Path:
    """Return the log directory for *project* (or a global dir when None).

    A supplied *project* is validated with
    [`_reject_unsafe_component`][terok.lib.util.output_capture._reject_unsafe_component]
    before it becomes a directory level, so the path stays under
    [`core_state_dir`][terok.lib.core.paths.core_state_dir].
    """
    from ..core.paths import core_state_dir

    base = core_state_dir()
    if not project:
        return base / "logs"
    _reject_unsafe_component(project, "project")
    return base / "projects" / project / "logs"


def _log_file_path(kind: str, project: str | None, task_id: str | None) -> Path:
    """Build a timestamped fallback log-file path for one *kind* of operation.

    *kind*, *project* and *task_id* are each validated with
    [`_reject_unsafe_component`][terok.lib.util.output_capture._reject_unsafe_component]
    (the latter two via [`_logs_dir`][terok.lib.util.output_capture._logs_dir])
    before interpolation, so the returned path always stays under the state dir.
    """
    _reject_unsafe_component(kind, "kind")
    if task_id:
        _reject_unsafe_component(task_id, "task_id")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{kind}-{task_id}-{stamp}" if task_id else f"{kind}-{stamp}"
    return _logs_dir(project) / f"{stem}.log"


@contextlib.contextmanager
def tee_output(
    kind: str, *, project: str | None = None, task_id: str | None = None
) -> Iterator[None]:
    """Capture a build/run operation's output to journald or a log file.

    Thin wrapper over
    [`terok_util.output_capture.tee_output`][terok_util.output_capture.tee_output]:
    labels the stream with terok's journald fields and resolves the
    file-fallback path lazily under the core state dir.

    Args:
        kind: Operation label — ``"build"``, ``"run"``, or ``"setup"``.
        project: Owning project name, when known.
        task_id: Owning task id, when known.
    """
    fields = {"TEROK_KIND": kind}
    if project:
        fields["TEROK_PROJECT"] = project
    if task_id:
        fields["TEROK_TASK"] = task_id
    with _util_tee_output(
        _IDENTIFIER,
        fields=fields,
        file_path_fn=lambda: _log_file_path(kind, project, task_id),
    ):
        yield


__all__ = ["tee_output"]
