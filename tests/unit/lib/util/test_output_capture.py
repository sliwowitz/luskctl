# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Tests for the terok output-capture glue over terok_util.tee_output."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from terok.lib.util import output_capture as oc


def test_log_file_path_shape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(oc, "_logs_dir", lambda project: tmp_path)
    run_path = oc._log_file_path("run", "proj", "t1")
    build_path = oc._log_file_path("build", "proj", None)
    assert run_path.name.startswith("run-t1-") and run_path.suffix == ".log"
    assert build_path.name.startswith("build-") and "None" not in build_path.name


@pytest.mark.parametrize(
    "task_id",
    [
        pytest.param("../../etc/cron.d/x", id="relative-traversal"),
        pytest.param("..", id="bare-parent"),
        pytest.param(".", id="bare-dot"),
        pytest.param("/etc/passwd", id="absolute-path"),
        pytest.param("a/b", id="embedded-separator"),
        pytest.param("has\0nul", id="nul-byte"),
    ],
)
def test_log_file_path_rejects_traversal_task_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, task_id: str
) -> None:
    """A *task_id* that could escape the log tree is rejected, not interpolated."""
    monkeypatch.setattr(oc, "_logs_dir", lambda project: tmp_path)
    with pytest.raises(ValueError, match="unsafe task_id"):
        oc._log_file_path("run", "proj", task_id)


@pytest.mark.parametrize(
    "kind",
    [
        pytest.param("../evil", id="relative-traversal"),
        pytest.param("..", id="bare-parent"),
        pytest.param("/abs", id="absolute-path"),
        pytest.param("build\0", id="nul-byte"),
    ],
)
def test_log_file_path_rejects_unsafe_kind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    """An unsafe *kind* label is rejected the same way as *task_id*."""
    monkeypatch.setattr(oc, "_logs_dir", lambda project: tmp_path)
    with pytest.raises(ValueError, match="unsafe kind"):
        oc._log_file_path(kind, "proj", "t1")


def test_log_file_path_stays_within_logs_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Valid components resolve strictly under ``_logs_dir`` — no escape."""
    logs = tmp_path / "logs"
    monkeypatch.setattr(oc, "_logs_dir", lambda project: logs)
    path = oc._log_file_path("run", "proj", "t1")
    assert path.parent == logs
    assert logs in path.resolve().parents


def test_logs_dir_scopes_by_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("terok.lib.core.paths.core_state_dir", lambda: tmp_path)
    assert oc._logs_dir("proj") == tmp_path / "projects" / "proj" / "logs"
    assert oc._logs_dir(None) == tmp_path / "logs"


@pytest.mark.parametrize(
    "project",
    [
        pytest.param("../evil", id="relative-traversal"),
        pytest.param("..", id="bare-parent"),
        pytest.param("/abs", id="absolute-path"),
        pytest.param("a/b", id="embedded-separator"),
        pytest.param("has\0nul", id="nul-byte"),
    ],
)
def test_logs_dir_rejects_unsafe_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, project: str
) -> None:
    """An unsafe *project* now fails loud too — same guard as kind/task_id."""
    monkeypatch.setattr("terok.lib.core.paths.core_state_dir", lambda: tmp_path)
    with pytest.raises(ValueError, match="unsafe project"):
        oc._logs_dir(project)


def test_tee_output_delegates_and_persists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    log_path = tmp_path / "run.log"
    monkeypatch.setattr(oc, "_log_file_path", lambda kind, project, task_id: log_path)
    from terok_util import output_capture as util_oc

    monkeypatch.setattr(util_oc, "journald_available", lambda: False)

    with oc.tee_output("run", project="proj", task_id="t1"):
        os.write(1, b"hello-capture\n")
        subprocess.run(["printf", "sub-line\\n"], check=True)

    live = capfd.readouterr()
    logged = log_path.read_text()
    assert "hello-capture" in live.out and "sub-line" in live.out
    assert "hello-capture" in logged and "sub-line" in logged
