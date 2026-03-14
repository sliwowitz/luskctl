# SPDX-FileCopyrightText: 2025 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Tests for shield CLI commands (registry-driven dispatch)."""

import argparse
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from terok_shield import ExecError

from terok.cli.commands.shield import _resolve_task, dispatch, register
from testfs import MOCK_TASK_DIR_1


class TestRegister:
    """Tests for register() building subparsers from COMMANDS."""

    def setup_method(self, method: object) -> None:
        """Create a parser with shield subparsers."""
        self.parser = argparse.ArgumentParser()
        subs = self.parser.add_subparsers(dest="cmd")
        register(subs)

    def test_status_without_task(self) -> None:
        """status subcommand parses without project/task."""
        args = self.parser.parse_args(["shield", "status"])
        assert args.shield_cmd == "status"

    def test_status_with_task(self) -> None:
        """status with project_id and task_id queries container state."""
        args = self.parser.parse_args(["shield", "status", "proj", "1"])
        assert args.shield_cmd == "status"
        assert args.project_id == "proj"
        assert args.task_id == "1"

    def test_allow_subcommand(self) -> None:
        """allow requires project_id, task_id, and target."""
        args = self.parser.parse_args(["shield", "allow", "proj", "task1", "example.com"])
        assert args.shield_cmd == "allow"
        assert args.project_id == "proj"
        assert args.task_id == "task1"
        assert args.target == "example.com"

    def test_deny_subcommand(self) -> None:
        """deny requires project_id, task_id, and target."""
        args = self.parser.parse_args(["shield", "deny", "proj", "task1", "example.com"])
        assert args.shield_cmd == "deny"

    def test_down_subcommand(self) -> None:
        """down accepts project_id, task_id, and optional --all."""
        args = self.parser.parse_args(["shield", "down", "proj", "task1", "--all"])
        assert args.shield_cmd == "down"
        assert args.allow_all

    def test_up_subcommand(self) -> None:
        """up requires project_id and task_id."""
        args = self.parser.parse_args(["shield", "up", "proj", "task1"])
        assert args.shield_cmd == "up"

    def test_rules_subcommand(self) -> None:
        """rules requires project_id and task_id."""
        args = self.parser.parse_args(["shield", "rules", "proj", "task1"])
        assert args.shield_cmd == "rules"

    def test_profiles_subcommand(self) -> None:
        """profiles subcommand has no project/task args."""
        args = self.parser.parse_args(["shield", "profiles"])
        assert args.shield_cmd == "profiles"
        assert not hasattr(args, "project_id")

    def test_standalone_only_excluded(self) -> None:
        """prepare, run, resolve are not registered (standalone_only)."""
        for cmd in ("prepare", "run", "resolve"):
            with pytest.raises(SystemExit):
                self.parser.parse_args(["shield", cmd])


class TestDispatch:
    """Tests for dispatch()."""

    def test_wrong_cmd_returns_false(self) -> None:
        """dispatch returns False for non-shield commands."""
        args = argparse.Namespace(cmd="project")
        assert not dispatch(args)

    @patch("terok.cli.commands.shield.make_shield")
    def test_status_without_task(self, mock_make: MagicMock) -> None:
        """dispatch handles bare status (no task) via registry handler."""
        mock_shield = MagicMock()
        mock_shield.status.return_value = {
            "mode": "hook",
            "profiles": ["dev-standard"],
            "audit_enabled": True,
        }
        mock_make.return_value = mock_shield

        args = argparse.Namespace(cmd="shield", shield_cmd="status")
        with patch("sys.stdout", new_callable=StringIO) as out:
            result = dispatch(args)

        assert result
        output = out.getvalue()
        assert "Mode" in output
        assert "hook" in output

    def test_partial_task_selector_exits(self) -> None:
        """Providing project_id without task_id exits with error."""
        args = argparse.Namespace(
            cmd="shield", shield_cmd="status", project_id="proj", task_id=None
        )
        with (
            patch("sys.stderr", new_callable=StringIO) as err,
            pytest.raises(SystemExit) as ctx,
        ):
            dispatch(args)

        assert ctx.value.code == 1
        assert "both" in err.getvalue()

    @patch("terok.cli.commands.shield._resolve_task")
    @patch("terok.cli.commands.shield.make_shield")
    def test_status_with_task(self, mock_make: MagicMock, mock_resolve: MagicMock) -> None:
        """dispatch handles status with project/task — queries container state."""
        mock_resolve.return_value = ("proj-cli-1", str(MOCK_TASK_DIR_1))
        mock_shield = MagicMock()
        mock_shield.state.return_value = MagicMock(value="up")
        mock_make.return_value = mock_shield

        args = argparse.Namespace(cmd="shield", shield_cmd="status", project_id="proj", task_id="1")
        with patch("sys.stdout", new_callable=StringIO) as out:
            result = dispatch(args)

        assert result
        assert "up" in out.getvalue()
        mock_shield.state.assert_called_once_with("proj-cli-1")

    @patch("terok.cli.commands.shield.make_shield")
    def test_preview_all_without_down_prints_error(self, mock_make: MagicMock) -> None:
        """preview --all without --down prints clean error to stderr."""
        mock_shield = MagicMock()
        mock_shield.preview.side_effect = ValueError("--all requires --down")
        mock_make.return_value = mock_shield

        args = argparse.Namespace(cmd="shield", shield_cmd="preview", down=False, allow_all=True)
        with (
            patch("sys.stderr", new_callable=StringIO) as err,
            pytest.raises(SystemExit) as ctx,
        ):
            dispatch(args)

        assert ctx.value.code == 1
        assert "--all requires --down" in err.getvalue()

    @patch("terok.cli.commands.shield._resolve_task")
    @patch("terok.cli.commands.shield.make_shield")
    def test_exec_error_prints_not_running(
        self, mock_make: MagicMock, mock_resolve: MagicMock
    ) -> None:
        """ExecError from nft produces a 'not running' message."""
        mock_resolve.return_value = ("proj-cli-1", str(MOCK_TASK_DIR_1))
        mock_shield = MagicMock()
        mock_shield.state.side_effect = ExecError(["nft", "list"], 1, "no such process")
        mock_make.return_value = mock_shield

        args = argparse.Namespace(cmd="shield", shield_cmd="status", project_id="proj", task_id="1")
        with (
            patch("sys.stderr", new_callable=StringIO) as err,
            pytest.raises(SystemExit) as ctx,
        ):
            dispatch(args)

        assert ctx.value.code == 1
        assert "not running" in err.getvalue()

    @patch("terok.cli.commands.shield._resolve_task")
    @patch("terok.cli.commands.shield.make_shield")
    def test_runtime_error_prints_message(
        self, mock_make: MagicMock, mock_resolve: MagicMock
    ) -> None:
        """RuntimeError from handler is caught and printed cleanly."""
        mock_resolve.return_value = ("proj-cli-1", str(MOCK_TASK_DIR_1))
        mock_shield = MagicMock()
        mock_shield.allow.side_effect = RuntimeError("No IPs allowed for proj-cli-1")
        mock_make.return_value = mock_shield

        args = argparse.Namespace(
            cmd="shield",
            shield_cmd="allow",
            project_id="proj",
            task_id="1",
            target="example.com",
        )
        with (
            patch("sys.stderr", new_callable=StringIO) as err,
            pytest.raises(SystemExit) as ctx,
        ):
            dispatch(args)

        assert ctx.value.code == 1
        assert "No IPs allowed" in err.getvalue()


class TestSetupSubcommand:
    """Tests for the manually registered setup subcommand."""

    def setup_method(self, method: object) -> None:
        """Create a parser with shield subparsers."""
        self.parser = argparse.ArgumentParser()
        subs = self.parser.add_subparsers(dest="cmd")
        register(subs)

    def test_setup_registered(self) -> None:
        """setup subcommand is registered and parses."""
        args = self.parser.parse_args(["shield", "setup"])
        assert args.shield_cmd == "setup"

    def test_setup_root_flag(self) -> None:
        """setup --root flag is parsed."""
        args = self.parser.parse_args(["shield", "setup", "--root"])
        assert args.root
        assert not args.user

    def test_setup_user_flag(self) -> None:
        """setup --user flag is parsed."""
        args = self.parser.parse_args(["shield", "setup", "--user"])
        assert not args.root
        assert args.user


class TestSetupDispatch:
    """Tests for setup command dispatch."""

    @patch("terok.lib.facade.shield_run_setup")
    def test_setup_root_dispatch(self, mock_setup: MagicMock) -> None:
        """dispatch calls shield_run_setup(root=True) for --root."""
        args = argparse.Namespace(cmd="shield", shield_cmd="setup", root=True, user=False)
        result = dispatch(args)
        assert result
        mock_setup.assert_called_once_with(root=True, user=False)

    @patch("terok.lib.facade.shield_run_setup")
    def test_setup_user_dispatch(self, mock_setup: MagicMock) -> None:
        """dispatch calls shield_run_setup(user=True) for --user."""
        args = argparse.Namespace(cmd="shield", shield_cmd="setup", root=False, user=True)
        result = dispatch(args)
        assert result
        mock_setup.assert_called_once_with(root=False, user=True)


class TestResolveTask:
    """Tests for _resolve_task()."""

    @patch("terok.lib.containers.tasks.load_task_meta", return_value=({"mode": None}, None))
    @patch("terok.lib.core.projects.load_project")
    def test_never_run_task_raises(self, mock_proj: MagicMock, _meta: MagicMock) -> None:
        """Task with mode=None raises ValueError."""
        mock_proj.return_value = MagicMock(id="proj")
        with pytest.raises(ValueError, match="has never been run"):
            _resolve_task("proj", "1")
