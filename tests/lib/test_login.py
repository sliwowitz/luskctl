import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import yaml

from luskctl.lib.containers.tasks import get_login_command, task_login, task_new
from test_utils import mock_git_config, write_project


class LoginTests(unittest.TestCase):
    """Tests for task_login, get_login_command, and _validate_login."""

    def _setup_project_with_task(
        self, base: Path, project_id: str, *, mode: str | None = None
    ) -> Path:
        """Create a project and task, optionally setting the mode in metadata."""
        config_root = base / "config"
        state_dir = base / "state"
        config_root.mkdir(parents=True, exist_ok=True)

        write_project(
            config_root,
            project_id,
            f"project:\n  id: {project_id}\n",
        )

        with unittest.mock.patch.dict(
            os.environ,
            {
                "LUSKCTL_CONFIG_DIR": str(config_root),
                "LUSKCTL_STATE_DIR": str(state_dir),
            },
        ):
            task_new(project_id)

        if mode:
            meta_dir = state_dir / "projects" / project_id / "tasks"
            meta_path = meta_dir / "1.yml"
            meta = yaml.safe_load(meta_path.read_text())
            meta["mode"] = mode
            meta_path.write_text(yaml.safe_dump(meta))

        return state_dir

    def test_task_login_unknown_task(self) -> None:
        """task_login raises SystemExit for non-existent task."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_login_unknown"
            write_project(
                config_root,
                project_id,
                f"project:\n  id: {project_id}\n",
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                },
            ):
                with self.assertRaises(SystemExit) as ctx:
                    task_login(project_id, "999")
                self.assertIn("Unknown task", str(ctx.exception))

    def test_task_login_no_mode(self) -> None:
        """task_login raises SystemExit when task has never been run (no mode)."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            state_dir = self._setup_project_with_task(base, "proj_login_nomode")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                },
            ):
                with self.assertRaises(SystemExit) as ctx:
                    task_login("proj_login_nomode", "1")
                self.assertIn("never been run", str(ctx.exception))

    def test_task_login_container_not_found(self) -> None:
        """task_login raises SystemExit when container does not exist."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            state_dir = self._setup_project_with_task(base, "proj_login_nf", mode="cli")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                },
            ):
                with unittest.mock.patch(
                    "luskctl.lib.containers.tasks.get_container_state", return_value=None
                ):
                    with self.assertRaises(SystemExit) as ctx:
                        task_login("proj_login_nf", "1")
                    self.assertIn("does not exist", str(ctx.exception))

    def test_task_login_container_not_running(self) -> None:
        """task_login raises SystemExit when container is not running."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            state_dir = self._setup_project_with_task(base, "proj_login_nr", mode="cli")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                },
            ):
                with unittest.mock.patch(
                    "luskctl.lib.containers.tasks.get_container_state", return_value="exited"
                ):
                    with self.assertRaises(SystemExit) as ctx:
                        task_login("proj_login_nr", "1")
                    self.assertIn("not running", str(ctx.exception))

    def test_task_login_success(self) -> None:
        """task_login calls os.execvp with correct podman+tmux command."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            state_dir = self._setup_project_with_task(base, "proj_login_ok", mode="cli")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                },
            ):
                with (
                    unittest.mock.patch(
                        "luskctl.lib.containers.tasks.get_container_state",
                        return_value="running",
                    ),
                    unittest.mock.patch("luskctl.lib.containers.tasks.os.execvp") as mock_exec,
                ):
                    task_login("proj_login_ok", "1")

                    mock_exec.assert_called_once_with(
                        "podman",
                        [
                            "podman",
                            "exec",
                            "-it",
                            "proj_login_ok-cli-1",
                            "tmux",
                            "new-session",
                            "-A",
                            "-s",
                            "main",
                        ],
                    )

    def test_get_login_command_returns_list(self) -> None:
        """get_login_command returns correct command list for CLI-mode task."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            state_dir = self._setup_project_with_task(base, "proj_logincmd", mode="cli")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                },
            ):
                with unittest.mock.patch(
                    "luskctl.lib.containers.tasks.get_container_state",
                    return_value="running",
                ):
                    cmd = get_login_command("proj_logincmd", "1")
                    self.assertEqual(
                        cmd,
                        [
                            "podman",
                            "exec",
                            "-it",
                            "proj_logincmd-cli-1",
                            "tmux",
                            "new-session",
                            "-A",
                            "-s",
                            "main",
                        ],
                    )

    def test_get_login_command_web_mode(self) -> None:
        """get_login_command uses web mode container name when mode is web."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            state_dir = self._setup_project_with_task(base, "proj_loginweb", mode="web")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(base / "config"),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                },
            ):
                with unittest.mock.patch(
                    "luskctl.lib.containers.tasks.get_container_state",
                    return_value="running",
                ):
                    cmd = get_login_command("proj_loginweb", "1")
                    self.assertEqual(cmd[3], "proj_loginweb-web-1")

    def test_login_no_longer_injects_agent_config(self) -> None:
        """get_login_command does NOT inject agent config (handled via mount)."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            write_project(
                config_root,
                "proj_login_cfg",
                "project:\n  id: proj_login_cfg\nagent:\n  model: sonnet\n",
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                },
            ):
                task_new("proj_login_cfg")

            meta_dir = state_dir / "projects" / "proj_login_cfg" / "tasks"
            meta_path = meta_dir / "1.yml"
            meta = yaml.safe_load(meta_path.read_text())
            meta["mode"] = "cli"
            meta_path.write_text(yaml.safe_dump(meta))

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                },
            ):
                with (
                    unittest.mock.patch(
                        "luskctl.lib.containers.tasks.get_container_state",
                        return_value="running",
                    ),
                    mock_git_config(),
                    unittest.mock.patch("luskctl.lib.containers.tasks.subprocess.run") as mock_run,
                ):
                    cmd = get_login_command("proj_login_cfg", "1")

                    # Should still return the tmux command
                    self.assertEqual(cmd[3], "proj_login_cfg-cli-1")
                    self.assertIn("tmux", cmd)

                    # No podman exec/cp calls --- config injection is via mount
                    mock_run.assert_not_called()
