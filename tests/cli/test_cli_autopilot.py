"""Tests for autopilot CLI commands: run-claude, login-claude."""

import unittest
import unittest.mock

from luskctl.cli.main import main


class RunClaudeCliTests(unittest.TestCase):
    """Tests for luskctl run-claude argument parsing."""

    def test_run_claude_requires_project_and_prompt(self) -> None:
        """run-claude requires project_id and prompt arguments."""
        with (
            unittest.mock.patch("sys.argv", ["luskctl", "run-claude"]),
            self.assertRaises(SystemExit) as ctx,
        ):
            main()
        # argparse exits with code 2 for missing required args
        self.assertEqual(ctx.exception.code, 2)

    def test_run_claude_dispatches_to_task_run_headless(self) -> None:
        """run-claude dispatches to task_run_headless with correct args."""
        with (
            unittest.mock.patch(
                "sys.argv",
                [
                    "luskctl",
                    "run-claude",
                    "myproject",
                    "Fix the auth bug",
                    "--model",
                    "opus",
                    "--max-turns",
                    "50",
                    "--timeout",
                    "3600",
                ],
            ),
            unittest.mock.patch("luskctl.cli.main.task_run_headless") as mock_run,
        ):
            main()
            mock_run.assert_called_once_with(
                "myproject",
                "Fix the auth bug",
                config_path=None,
                model="opus",
                max_turns=50,
                timeout=3600,
                follow=True,
            )

    def test_run_claude_no_follow_flag(self) -> None:
        """run-claude --no-follow passes follow=False."""
        with (
            unittest.mock.patch(
                "sys.argv",
                ["luskctl", "run-claude", "myproject", "test", "--no-follow"],
            ),
            unittest.mock.patch("luskctl.cli.main.task_run_headless") as mock_run,
        ):
            main()
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args
            # follow should be False
            self.assertFalse(call_kwargs[1]["follow"])

    def test_run_claude_with_config(self) -> None:
        """run-claude --config passes config_path."""
        with (
            unittest.mock.patch(
                "sys.argv",
                [
                    "luskctl",
                    "run-claude",
                    "myproject",
                    "test",
                    "--config",
                    "/path/to/agent.json",
                ],
            ),
            unittest.mock.patch("luskctl.cli.main.task_run_headless") as mock_run,
        ):
            main()
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args
            self.assertEqual(call_kwargs[1]["config_path"], "/path/to/agent.json")


class LoginClaudeCliTests(unittest.TestCase):
    """Tests for luskctl login-claude argument parsing."""

    def test_login_claude_requires_project_and_task(self) -> None:
        """login-claude requires project_id and task_id arguments."""
        with (
            unittest.mock.patch("sys.argv", ["luskctl", "login-claude"]),
            self.assertRaises(SystemExit) as ctx,
        ):
            main()
        self.assertEqual(ctx.exception.code, 2)

    def test_login_claude_dispatches_correctly(self) -> None:
        """login-claude dispatches to task_login_claude with correct args."""
        with (
            unittest.mock.patch(
                "sys.argv",
                ["luskctl", "login-claude", "myproject", "3", "--config", "/path/to/cfg.json"],
            ),
            unittest.mock.patch("luskctl.cli.main.task_login_claude") as mock_login,
        ):
            main()
            mock_login.assert_called_once_with(
                "myproject",
                "3",
                config_path="/path/to/cfg.json",
            )

    def test_login_claude_no_config(self) -> None:
        """login-claude works without --config flag."""
        with (
            unittest.mock.patch(
                "sys.argv",
                ["luskctl", "login-claude", "myproject", "1"],
            ),
            unittest.mock.patch("luskctl.cli.main.task_login_claude") as mock_login,
        ):
            main()
            mock_login.assert_called_once_with(
                "myproject",
                "1",
                config_path=None,
            )
