"""Tests for autopilot CLI commands: run-claude."""

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
                agents=None,
                preset=None,
                name=None,
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
                    "/path/to/agent.yml",
                ],
            ),
            unittest.mock.patch("luskctl.cli.main.task_run_headless") as mock_run,
        ):
            main()
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args
            self.assertEqual(call_kwargs[1]["config_path"], "/path/to/agent.yml")

    def test_run_claude_with_agent_selection(self) -> None:
        """run-claude --agent passes agents list to task_run_headless."""
        with (
            unittest.mock.patch(
                "sys.argv",
                [
                    "luskctl",
                    "run-claude",
                    "myproject",
                    "test",
                    "--agent",
                    "debugger",
                    "--agent",
                    "planner",
                ],
            ),
            unittest.mock.patch("luskctl.cli.main.task_run_headless") as mock_run,
        ):
            main()
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args
            self.assertEqual(call_kwargs[1]["agents"], ["debugger", "planner"])

    def test_task_run_cli_with_agent_selection(self) -> None:
        """task run-cli --agent passes agents to task_run_cli."""
        with (
            unittest.mock.patch(
                "sys.argv",
                ["luskctl", "task", "run-cli", "myproject", "1", "--agent", "debugger"],
            ),
            unittest.mock.patch("luskctl.cli.main.task_run_cli") as mock_run,
        ):
            main()
            mock_run.assert_called_once_with(
                "myproject",
                "1",
                agents=["debugger"],
                preset=None,
            )

    def test_task_run_web_with_agent_selection(self) -> None:
        """task run-web --agent passes agents to task_run_web."""
        with (
            unittest.mock.patch(
                "sys.argv",
                ["luskctl", "task", "run-web", "myproject", "1", "--agent", "reviewer"],
            ),
            unittest.mock.patch("luskctl.cli.main.task_run_web") as mock_run,
        ):
            main()
            mock_run.assert_called_once_with(
                "myproject",
                "1",
                backend=None,
                agents=["reviewer"],
                preset=None,
            )
