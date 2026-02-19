"""Tests for autopilot (Level 1+2) features: run-claude, login-claude, agent config."""

import os
import subprocess
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import yaml

from luskctl.lib.containers import _get_container_exit_code, _stream_until_exit
from luskctl.lib.projects import load_project
from luskctl.lib.tasks import (
    task_login_claude,
    task_new,
    task_run_headless,
)
from test_utils import mock_git_config, write_project


class AgentConfigProjectTests(unittest.TestCase):
    """Tests for agent config parsing in projects.py."""

    def test_agent_default_config_none_when_absent(self) -> None:
        """Project has agent_default_config=None when not configured."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj_noagent", "project:\n  id: proj_noagent\n")

            with unittest.mock.patch.dict(
                os.environ,
                {"LUSKCTL_CONFIG_DIR": str(config_root), "LUSKCTL_STATE_DIR": str(base / "s")},
            ):
                with mock_git_config():
                    p = load_project("proj_noagent")
                self.assertIsNone(p.agent_default_config)

    def test_agent_default_config_parsed(self) -> None:
        """Project parses agent.default_config path from project.yml."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            config_file = base / "agent-config.json"
            config_file.write_text('{"model": "sonnet"}', encoding="utf-8")

            write_project(
                config_root,
                "proj_agent",
                f"project:\n  id: proj_agent\nagent:\n  default_config: {config_file}\n",
            )

            with unittest.mock.patch.dict(
                os.environ,
                {"LUSKCTL_CONFIG_DIR": str(config_root), "LUSKCTL_STATE_DIR": str(base / "s")},
            ):
                with mock_git_config():
                    p = load_project("proj_agent")
                self.assertIsNotNone(p.agent_default_config)
                self.assertEqual(p.agent_default_config, config_file.resolve())


class StreamUntilExitTests(unittest.TestCase):
    """Tests for _stream_until_exit and _get_container_exit_code."""

    def test_get_container_exit_code_success(self) -> None:
        with unittest.mock.patch(
            "luskctl.lib.containers.subprocess.check_output", return_value="0\n"
        ):
            code = _get_container_exit_code("test-container")
            self.assertEqual(code, 0)

    def test_get_container_exit_code_nonzero(self) -> None:
        with unittest.mock.patch(
            "luskctl.lib.containers.subprocess.check_output", return_value="1\n"
        ):
            code = _get_container_exit_code("test-container")
            self.assertEqual(code, 1)

    def test_get_container_exit_code_error(self) -> None:
        with unittest.mock.patch(
            "luskctl.lib.containers.subprocess.check_output",
            side_effect=subprocess.CalledProcessError(1, "podman"),
        ):
            code = _get_container_exit_code("test-container")
            self.assertEqual(code, -1)

    def test_stream_until_exit_calls_stream_and_exit_code(self) -> None:
        with (
            unittest.mock.patch(
                "luskctl.lib.containers._stream_initial_logs", return_value=False
            ) as mock_stream,
            unittest.mock.patch(
                "luskctl.lib.containers._get_container_exit_code", return_value=0
            ) as mock_exit,
        ):
            code = _stream_until_exit("test-container")
            self.assertEqual(code, 0)
            mock_stream.assert_called_once()
            # Verify ready_check always returns False
            call_kwargs = mock_stream.call_args
            ready_fn = call_kwargs[1]["ready_check"] if call_kwargs[1] else call_kwargs[0][2]
            self.assertFalse(ready_fn("any line"))
            mock_exit.assert_called_once_with("test-container")


class TaskRunHeadlessTests(unittest.TestCase):
    """Tests for task_run_headless."""

    def _make_project(self, base: Path, project_id: str, extra_yml: str = "") -> Path:
        config_root = base / "config"
        envs_dir = base / "envs"
        config_root.mkdir(parents=True, exist_ok=True)
        config_file = base / "config.yml"
        config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")
        write_project(
            config_root,
            project_id,
            f"project:\n  id: {project_id}\n{extra_yml}",
        )
        return config_file

    def test_headless_creates_task_and_writes_prompt(self) -> None:
        """task_run_headless creates a task with prompt.txt in agent-config dir."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_file = self._make_project(base, "proj_hl")
            state_dir = base / "state"

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
                clear=True,
            ):
                with (
                    mock_git_config(),
                    unittest.mock.patch("luskctl.lib.tasks.subprocess.run") as run_mock,
                    unittest.mock.patch("luskctl.lib.tasks._stream_until_exit", return_value=0),
                    unittest.mock.patch("luskctl.lib.tasks._print_run_summary"),
                ):
                    run_mock.return_value = subprocess.CompletedProcess([], 0)
                    buffer = StringIO()
                    with redirect_stdout(buffer):
                        task_id = task_run_headless("proj_hl", "Fix the auth bug")

                    self.assertEqual(task_id, "1")

                    # Verify prompt file was written
                    agent_config_dir = state_dir / "tasks" / "proj_hl" / "1" / "agent-config"
                    self.assertTrue(agent_config_dir.is_dir())
                    prompt_file = agent_config_dir / "prompt.txt"
                    self.assertTrue(prompt_file.is_file())
                    self.assertEqual(prompt_file.read_text(), "Fix the auth bug")

    def test_headless_mounts_agent_config_dir(self) -> None:
        """task_run_headless mounts agent-config dir to /home/dev/.luskctl."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_file = self._make_project(base, "proj_mount")
            state_dir = base / "state"

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
                clear=True,
            ):
                with (
                    mock_git_config(),
                    unittest.mock.patch("luskctl.lib.tasks.subprocess.run") as run_mock,
                    unittest.mock.patch("luskctl.lib.tasks._stream_until_exit", return_value=0),
                    unittest.mock.patch("luskctl.lib.tasks._print_run_summary"),
                ):
                    run_mock.return_value = subprocess.CompletedProcess([], 0)
                    buffer = StringIO()
                    with redirect_stdout(buffer):
                        task_run_headless("proj_mount", "test prompt")

                    # Check the podman run command has the agent-config mount
                    cmd = run_mock.call_args[0][0]
                    cmd_str = " ".join(cmd)
                    self.assertIn("/home/dev/.luskctl:Z", cmd_str)

    def test_headless_copies_config_file(self) -> None:
        """task_run_headless copies agent config when provided."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_file = self._make_project(base, "proj_cfg")
            state_dir = base / "state"

            agent_config = base / "my-agent-config.json"
            agent_config.write_text('{"model": "opus"}', encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
                clear=True,
            ):
                with (
                    mock_git_config(),
                    unittest.mock.patch("luskctl.lib.tasks.subprocess.run") as run_mock,
                    unittest.mock.patch("luskctl.lib.tasks._stream_until_exit", return_value=0),
                    unittest.mock.patch("luskctl.lib.tasks._print_run_summary"),
                ):
                    run_mock.return_value = subprocess.CompletedProcess([], 0)
                    buffer = StringIO()
                    with redirect_stdout(buffer):
                        task_run_headless("proj_cfg", "test prompt", config_path=str(agent_config))

                    # Verify config was copied
                    copied = (
                        state_dir
                        / "tasks"
                        / "proj_cfg"
                        / "1"
                        / "agent-config"
                        / "agent-config.json"
                    )
                    self.assertTrue(copied.is_file())
                    self.assertEqual(copied.read_text(), '{"model": "opus"}')

    def test_headless_sets_env_overrides(self) -> None:
        """task_run_headless passes model and max_turns as env vars."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_file = self._make_project(base, "proj_env")
            state_dir = base / "state"

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
                clear=True,
            ):
                with (
                    mock_git_config(),
                    unittest.mock.patch("luskctl.lib.tasks.subprocess.run") as run_mock,
                    unittest.mock.patch("luskctl.lib.tasks._stream_until_exit", return_value=0),
                    unittest.mock.patch("luskctl.lib.tasks._print_run_summary"),
                ):
                    run_mock.return_value = subprocess.CompletedProcess([], 0)
                    buffer = StringIO()
                    with redirect_stdout(buffer):
                        task_run_headless("proj_env", "test", model="opus", max_turns=50)

                    cmd = run_mock.call_args[0][0]
                    env_entries = {cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-e"}
                    self.assertIn("LUSKCTL_AGENT_MODEL=opus", env_entries)
                    self.assertIn("LUSKCTL_AGENT_MAX_TURNS=50", env_entries)

    def test_headless_container_name_uses_run_prefix(self) -> None:
        """task_run_headless names the container <project>-run-<task_id>."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_file = self._make_project(base, "proj_name")
            state_dir = base / "state"

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
                clear=True,
            ):
                with (
                    mock_git_config(),
                    unittest.mock.patch("luskctl.lib.tasks.subprocess.run") as run_mock,
                    unittest.mock.patch("luskctl.lib.tasks._stream_until_exit", return_value=0),
                    unittest.mock.patch("luskctl.lib.tasks._print_run_summary"),
                ):
                    run_mock.return_value = subprocess.CompletedProcess([], 0)
                    buffer = StringIO()
                    with redirect_stdout(buffer):
                        task_run_headless("proj_name", "test")

                    cmd = run_mock.call_args[0][0]
                    name_idx = cmd.index("--name")
                    self.assertEqual(cmd[name_idx + 1], "proj_name-run-1")

    def test_headless_metadata_updated(self) -> None:
        """task_run_headless sets mode=run and updates status on completion."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_file = self._make_project(base, "proj_meta")
            state_dir = base / "state"

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
                clear=True,
            ):
                with (
                    mock_git_config(),
                    unittest.mock.patch("luskctl.lib.tasks.subprocess.run") as run_mock,
                    unittest.mock.patch("luskctl.lib.tasks._stream_until_exit", return_value=0),
                    unittest.mock.patch("luskctl.lib.tasks._print_run_summary"),
                ):
                    run_mock.return_value = subprocess.CompletedProcess([], 0)
                    buffer = StringIO()
                    with redirect_stdout(buffer):
                        task_run_headless("proj_meta", "test")

                    meta_path = state_dir / "projects" / "proj_meta" / "tasks" / "1.yml"
                    meta = yaml.safe_load(meta_path.read_text())
                    self.assertEqual(meta["mode"], "run")
                    self.assertEqual(meta["status"], "completed")
                    self.assertEqual(meta["exit_code"], 0)

    def test_headless_no_follow_mode(self) -> None:
        """task_run_headless with follow=False prints detach info."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_file = self._make_project(base, "proj_nf")
            state_dir = base / "state"

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
                clear=True,
            ):
                with (
                    mock_git_config(),
                    unittest.mock.patch("luskctl.lib.tasks.subprocess.run") as run_mock,
                    unittest.mock.patch("luskctl.lib.tasks._stream_until_exit") as stream_mock,
                ):
                    run_mock.return_value = subprocess.CompletedProcess([], 0)
                    buffer = StringIO()
                    with redirect_stdout(buffer):
                        task_run_headless("proj_nf", "test", follow=False)

                    # Stream should NOT be called in no-follow mode
                    stream_mock.assert_not_called()

                    output = buffer.getvalue()
                    self.assertIn("detached", output.lower())
                    self.assertIn("proj_nf-run-1", output)

    def test_headless_uses_project_default_config(self) -> None:
        """task_run_headless falls back to project's agent_default_config."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            state_dir = base / "state"
            envs_dir = base / "envs"

            # Create a default config file
            default_config = base / "default-agent.json"
            default_config.write_text('{"model": "haiku"}', encoding="utf-8")

            config_root = base / "config"
            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")
            write_project(
                config_root,
                "proj_dc",
                (f"project:\n  id: proj_dc\nagent:\n  default_config: {default_config}\n"),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
                clear=True,
            ):
                with (
                    mock_git_config(),
                    unittest.mock.patch("luskctl.lib.tasks.subprocess.run") as run_mock,
                    unittest.mock.patch("luskctl.lib.tasks._stream_until_exit", return_value=0),
                    unittest.mock.patch("luskctl.lib.tasks._print_run_summary"),
                ):
                    run_mock.return_value = subprocess.CompletedProcess([], 0)
                    buffer = StringIO()
                    with redirect_stdout(buffer):
                        task_run_headless("proj_dc", "test prompt")

                    # Verify default config was copied
                    copied = (
                        state_dir / "tasks" / "proj_dc" / "1" / "agent-config" / "agent-config.json"
                    )
                    self.assertTrue(copied.is_file())
                    self.assertEqual(copied.read_text(), '{"model": "haiku"}')

    def test_headless_uses_start_claude_in_command(self) -> None:
        """task_run_headless podman command invokes start-claude.sh."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_file = self._make_project(base, "proj_cmd")
            state_dir = base / "state"

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
                clear=True,
            ):
                with (
                    mock_git_config(),
                    unittest.mock.patch("luskctl.lib.tasks.subprocess.run") as run_mock,
                    unittest.mock.patch("luskctl.lib.tasks._stream_until_exit", return_value=0),
                    unittest.mock.patch("luskctl.lib.tasks._print_run_summary"),
                ):
                    run_mock.return_value = subprocess.CompletedProcess([], 0)
                    buffer = StringIO()
                    with redirect_stdout(buffer):
                        task_run_headless("proj_cmd", "test")

                    cmd = run_mock.call_args[0][0]
                    # The last arg should be a bash command that includes start-claude.sh
                    bash_cmd = cmd[-1]
                    self.assertIn("init-ssh-and-repo.sh", bash_cmd)
                    self.assertIn("start-claude.sh", bash_cmd)
                    self.assertIn("timeout", bash_cmd)


class TaskLoginClaudeTests(unittest.TestCase):
    """Tests for task_login_claude."""

    def _setup_project_with_task(self, base: Path, project_id: str, *, mode: str = "cli") -> Path:
        config_root = base / "config"
        state_dir = base / "state"
        config_root.mkdir(parents=True, exist_ok=True)
        write_project(config_root, project_id, f"project:\n  id: {project_id}\n")

        with unittest.mock.patch.dict(
            os.environ,
            {
                "LUSKCTL_CONFIG_DIR": str(config_root),
                "LUSKCTL_STATE_DIR": str(state_dir),
            },
        ):
            task_new(project_id)

        meta_dir = state_dir / "projects" / project_id / "tasks"
        meta_path = meta_dir / "1.yml"
        meta = yaml.safe_load(meta_path.read_text())
        meta["mode"] = mode
        meta_path.write_text(yaml.safe_dump(meta))

        return state_dir

    def test_login_claude_calls_execvp(self) -> None:
        """task_login_claude exec's into container with start-claude.sh."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            state_dir = self._setup_project_with_task(base, "proj_lc", mode="cli")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                },
            ):
                with (
                    unittest.mock.patch(
                        "luskctl.lib.tasks._get_container_state",
                        return_value="running",
                    ),
                    unittest.mock.patch("luskctl.lib.tasks.os.execvp") as mock_exec,
                ):
                    task_login_claude("proj_lc", "1")

                    mock_exec.assert_called_once_with(
                        "podman",
                        [
                            "podman",
                            "exec",
                            "-it",
                            "proj_lc-cli-1",
                            "bash",
                            "-lc",
                            "start-claude.sh",
                        ],
                    )

    def test_login_claude_copies_config(self) -> None:
        """task_login_claude copies config file when provided."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            state_dir = self._setup_project_with_task(base, "proj_lccfg", mode="cli")

            agent_config = base / "agent.json"
            agent_config.write_text('{"model": "opus"}', encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                },
            ):
                with (
                    mock_git_config(),
                    unittest.mock.patch(
                        "luskctl.lib.tasks._get_container_state",
                        return_value="running",
                    ),
                    unittest.mock.patch("luskctl.lib.tasks.os.execvp"),
                    unittest.mock.patch("luskctl.lib.tasks.subprocess.run") as mock_run,
                ):
                    mock_run.return_value = subprocess.CompletedProcess([], 0)
                    task_login_claude("proj_lccfg", "1", config_path=str(agent_config))

                    # Verify podman exec mkdir and podman cp were called
                    self.assertEqual(mock_run.call_count, 2)
                    mkdir_call = mock_run.call_args_list[0][0][0]
                    self.assertEqual(mkdir_call[:2], ["podman", "exec"])
                    self.assertIn("mkdir", mkdir_call)
                    cp_call = mock_run.call_args_list[1][0][0]
                    self.assertEqual(cp_call[:2], ["podman", "cp"])

    def test_login_claude_container_not_running(self) -> None:
        """task_login_claude raises SystemExit when container is not running."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            state_dir = self._setup_project_with_task(base, "proj_lcnr", mode="cli")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                },
            ):
                with unittest.mock.patch(
                    "luskctl.lib.tasks._get_container_state", return_value="exited"
                ):
                    with self.assertRaises(SystemExit) as ctx:
                        task_login_claude("proj_lcnr", "1")
                    self.assertIn("not running", str(ctx.exception))
