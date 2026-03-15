# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Tests for the integration test map generator."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from tests.testfs import MOCK_BASE


def _load_test_map_module() -> ModuleType:
    """Load ``docs/test_map.py`` as a module for direct function testing."""
    path = Path(__file__).resolve().parents[2] / "docs" / "test_map.py"
    spec = importlib.util.spec_from_file_location("test_map", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def test_map_module() -> ModuleType:
    """Return the loaded test-map module."""
    return _load_test_map_module()


def test_collect_tests_filters_output_and_uses_integration_dir(
    test_map_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Collection should call pytest on the integration dir and keep only node IDs."""
    fake_root = MOCK_BASE / "docs-root"
    fake_integration_dir = fake_root / "tests" / "integration"
    fake_venv_bin = MOCK_BASE / "venv" / "bin"
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "tests/integration/tasks/test_lifecycle.py::test_create\n"
                "tests/integration/cli/test_cli.py::TestCLI::test_help\n"
                "collected 2 items\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(test_map_module, "ROOT", fake_root)
    monkeypatch.setattr(test_map_module, "INTEGRATION_DIR", fake_integration_dir)
    monkeypatch.setattr(test_map_module, "_VENV_BIN", fake_venv_bin)
    monkeypatch.setattr(test_map_module.subprocess, "run", fake_run)

    assert test_map_module.collect_tests() == [
        "tests/integration/tasks/test_lifecycle.py::test_create",
        "tests/integration/cli/test_cli.py::TestCLI::test_help",
    ]
    assert calls == [
        (
            [
                str(fake_venv_bin / "pytest"),
                "--collect-only",
                "-qq",
                "-p",
                "no:tach",
                str(fake_integration_dir),
            ],
            {
                "capture_output": True,
                "text": True,
                "cwd": fake_root,
                "timeout": 60,
                "check": False,
            },
        )
    ]


def test_collect_tests_raises_with_pytest_output_on_failure(
    test_map_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Collection failures should surface pytest output for debugging."""
    monkeypatch.setattr(
        test_map_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=2,
            stdout="stdout details\n",
            stderr="stderr details\n",
        ),
    )

    with pytest.raises(RuntimeError, match="pytest collection failed \\(exit 2\\)"):
        test_map_module.collect_tests()


def test_group_by_directory_groups_root_and_subdirs(test_map_module: ModuleType) -> None:
    """Collected node IDs should be grouped by the first integration path segment."""
    groups = test_map_module._group_by_directory(
        [
            "tests/integration/tasks/test_lifecycle.py::test_create",
            "tests/integration/tasks/test_lifecycle.py::test_delete",
            "tests/integration/test_root.py::test_root_only",
        ]
    )

    assert groups == {
        "tasks": [
            "tests/integration/tasks/test_lifecycle.py::test_create",
            "tests/integration/tasks/test_lifecycle.py::test_delete",
        ],
        "(root)": ["tests/integration/test_root.py::test_root_only"],
    }


def test_sorted_dirs_orders_known_before_unknown(test_map_module: ModuleType) -> None:
    """Known directories should keep canonical order before unknown directories."""
    groups = {
        "launch": ["x"],
        "alpha": ["y"],
        "cli": ["z"],
        "projects": ["w"],
    }

    assert test_map_module._sorted_dirs(groups) == [
        "cli",
        "projects",
        "launch",
        "alpha",
    ]


@pytest.mark.parametrize(
    ("test_id", "expected"),
    [
        pytest.param(
            "tests/integration/tasks/test_lifecycle.py::TestLifecycle::test_create",
            "| `test_create` | `TestLifecycle` | `tests/integration/tasks/test_lifecycle.py` |",
            id="class-test",
        ),
        pytest.param(
            "tests/integration/test_root.py::test_root_only",
            "| `test_root_only` | `` | `tests/integration/test_root.py` |",
            id="module-test",
        ),
    ],
)
def test_format_test_row(test_map_module: ModuleType, test_id: str, expected: str) -> None:
    """Formatted rows should expose test, class, and file columns."""
    assert test_map_module._format_test_row(test_id) == expected


def test_generate_test_map_uses_collect_tests_when_needed(
    test_map_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The generator should collect tests on demand when none are provided."""
    test_ids = ["tests/integration/cli/test_cli.py::test_help"]
    monkeypatch.setattr(test_map_module, "collect_tests", lambda: test_ids)
    monkeypatch.setattr(test_map_module, "_dir_description", lambda _subdir: "")

    class FixedDateTime:
        """Minimal datetime stub returning a deterministic UTC timestamp."""

        @staticmethod
        def now(_tz: object) -> datetime:
            return datetime(2026, 3, 15, 12, 0, tzinfo=UTC)

    monkeypatch.setattr(test_map_module, "datetime", FixedDateTime)

    report = test_map_module.generate_test_map()

    assert "*Generated: 2026-03-15 12:00 UTC*" in report
    assert "**1 tests** across **1 directories**" in report
    assert "## `cli/`" in report
    assert "| `test_help` | `` | `tests/integration/cli/test_cli.py` |" in report


def test_generate_test_map_renders_directory_descriptions(
    test_map_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Directory descriptions should appear in their matching Markdown sections."""
    test_ids = [
        "tests/integration/tasks/test_lifecycle.py::test_create",
        "tests/integration/cli/test_cli.py::TestCLI::test_help",
    ]
    descriptions = {
        "cli": "CLI smoke coverage",
        "tasks": "Task lifecycle coverage",
    }

    monkeypatch.setattr(test_map_module, "_dir_description", descriptions.get)

    class FixedDateTime:
        """Minimal datetime stub returning a deterministic UTC timestamp."""

        @staticmethod
        def now(_tz: object) -> datetime:
            return datetime(2026, 3, 15, 13, 30, tzinfo=UTC)

    monkeypatch.setattr(test_map_module, "datetime", FixedDateTime)

    report = test_map_module.generate_test_map(test_ids)

    assert report.startswith("# Integration Test Map\n\n*Generated: 2026-03-15 13:30 UTC*")
    assert report.index("## `cli/`") < report.index("## `tasks/`")
    assert "CLI smoke coverage" in report
    assert "Task lifecycle coverage" in report
    assert "| `test_help` | `TestCLI` | `tests/integration/cli/test_cli.py` |" in report
    assert "| `test_create` | `` | `tests/integration/tasks/test_lifecycle.py` |" in report
