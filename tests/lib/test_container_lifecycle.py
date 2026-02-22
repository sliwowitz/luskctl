import os
import subprocess
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import yaml

from luskctl.lib.containers.runtime import get_container_state, get_task_container_state
from luskctl.lib.containers.task_runners import task_restart
from luskctl.lib.containers.tasks import task_new, task_status, task_stop
from test_utils import mock_git_config, write_project


class ContainerLifecycleTests(unittest.TestCase):
    """Tests for container lifecycle management: stop, restart, status."""

    def test_get_container_state_running(self) -> None:
        """_get_container_state returns 'running' for running container."""
        with unittest.mock.patch(
            "luskctl.lib.containers.runtime.subprocess.check_output", return_value="running\n"
        ):
            state = get_container_state("test-container")
            self.assertEqual(state, "running")

    def test_get_container_state_exited(self) -> None:
        """_get_container_state returns 'exited' for stopped container."""
        with unittest.mock.patch(
            "luskctl.lib.containers.runtime.subprocess.check_output", return_value="exited\n"
        ):
            state = get_container_state("test-container")
            self.assertEqual(state, "exited")

    def test_get_container_state_not_found(self) -> None:
        """_get_container_state returns None if container doesn't exist."""
        with unittest.mock.patch(
            "luskctl.lib.containers.runtime.subprocess.check_output",
            side_effect=subprocess.CalledProcessError(1, "podman"),
        ):
            state = get_container_state("test-container")
            self.assertIsNone(state)

    def test_get_container_state_podman_not_found(self) -> None:
        """_get_container_state returns None if podman is not installed."""
        with unittest.mock.patch(
            "luskctl.lib.containers.runtime.subprocess.check_output",
            side_effect=FileNotFoundError("podman"),
        ):
            state = get_container_state("test-container")
            self.assertIsNone(state)

    def test_task_stop_updates_metadata(self) -> None:
        """task_stop changes metadata status to 'stopped'."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_stop"
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
                # Create a task and simulate it's running
                task_new(project_id)
                meta_dir = state_dir / "projects" / project_id / "tasks"
                meta_path = meta_dir / "1.yml"

                # Update metadata to simulate a running CLI task
                meta = yaml.safe_load(meta_path.read_text())
                meta["status"] = "running"
                meta["mode"] = "cli"
                meta_path.write_text(yaml.safe_dump(meta))

                # Mock container is running and podman stop succeeds
                with (
                    mock_git_config(),
                    unittest.mock.patch(
                        "luskctl.lib.containers.tasks.get_container_state", return_value="running"
                    ),
                    unittest.mock.patch("luskctl.lib.containers.tasks.subprocess.run") as run_mock,
                ):
                    run_mock.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                    with redirect_stdout(StringIO()):
                        task_stop(project_id, "1")

                    # Verify podman stop was called
                    run_mock.assert_called()
                    call_args = run_mock.call_args[0][0]
                    self.assertEqual(call_args[:2], ["podman", "stop"])

                # Verify metadata status is now 'stopped'
                meta = yaml.safe_load(meta_path.read_text())
                self.assertEqual(meta["status"], "stopped")

    def test_task_stop_nonexistent_fails(self) -> None:
        """task_stop raises SystemExit if task doesn't exist."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_stop2"
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
                with mock_git_config():
                    with self.assertRaises(SystemExit) as ctx:
                        task_stop(project_id, "999")
                    self.assertIn("Unknown task", str(ctx.exception))

    def test_task_restart_starts_exited_container(self) -> None:
        """task_restart uses 'podman start' for exited container."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_restart"
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
                # Create a task and simulate it's stopped
                task_new(project_id)
                meta_dir = state_dir / "projects" / project_id / "tasks"
                meta_path = meta_dir / "1.yml"

                meta = yaml.safe_load(meta_path.read_text())
                meta["status"] = "stopped"
                meta["mode"] = "cli"
                meta_path.write_text(yaml.safe_dump(meta))

                # Mock container exists but is exited
                with (
                    mock_git_config(),
                    unittest.mock.patch(
                        "luskctl.lib.containers.task_runners.get_container_state",
                        side_effect=["exited", "running"],  # Stopped, then alive after start
                    ),
                    unittest.mock.patch(
                        "luskctl.lib.containers.task_runners.subprocess.run"
                    ) as run_mock,
                ):
                    run_mock.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                    with redirect_stdout(StringIO()):
                        task_restart(project_id, "1")

                    # Verify podman start was called
                    run_mock.assert_called()
                    call_args = run_mock.call_args[0][0]
                    self.assertEqual(call_args[:2], ["podman", "start"])

                # Verify metadata status is now 'running'
                meta = yaml.safe_load(meta_path.read_text())
                self.assertEqual(meta["status"], "running")

    def test_task_restart_already_running(self) -> None:
        """task_restart does nothing if container is already running."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_restart2"
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
                meta_dir = state_dir / "projects" / project_id / "tasks"
                meta_path = meta_dir / "1.yml"

                meta = yaml.safe_load(meta_path.read_text())
                meta["status"] = "running"
                meta["mode"] = "cli"
                meta_path.write_text(yaml.safe_dump(meta))

                # Mock container is already running
                with (
                    mock_git_config(),
                    unittest.mock.patch(
                        "luskctl.lib.containers.task_runners.get_container_state",
                        return_value="running",
                    ),
                    unittest.mock.patch(
                        "luskctl.lib.containers.task_runners.subprocess.run"
                    ) as run_mock,
                ):
                    output = StringIO()
                    with redirect_stdout(output):
                        task_restart(project_id, "1")

                        # Verify no podman command was called
                        run_mock.assert_not_called()

                        # Verify message indicates already running
                        self.assertIn("already running", output.getvalue())

    def test_task_status_shows_mismatch(self) -> None:
        """task_status detects metadata vs container state mismatch."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_status"
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
                meta_dir = state_dir / "projects" / project_id / "tasks"
                meta_path = meta_dir / "1.yml"

                meta = yaml.safe_load(meta_path.read_text())
                meta["status"] = "running"
                meta["mode"] = "cli"
                meta_path.write_text(yaml.safe_dump(meta))

                # Mock container is not running (mismatch)
                with (
                    mock_git_config(),
                    unittest.mock.patch(
                        "luskctl.lib.containers.tasks.get_container_state", return_value="exited"
                    ),
                ):
                    output = StringIO()
                    with redirect_stdout(output):
                        task_status(project_id, "1")

                    output_str = output.getvalue()
                    self.assertIn("exited", output_str)
                    self.assertIn("Warning", output_str)

    def test_get_task_container_state_no_mode(self) -> None:
        """get_task_container_state returns None if mode is not set."""
        state = get_task_container_state("proj", "1", None)
        self.assertIsNone(state)

    def test_get_task_container_state_with_mode(self) -> None:
        """get_task_container_state checks container state when mode is set."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_tui"
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
                with (
                    mock_git_config(),
                    unittest.mock.patch(
                        "luskctl.lib.containers.runtime.get_container_state",
                        return_value="running",
                    ) as mock_state,
                ):
                    state = get_task_container_state(project_id, "1", "cli")
                    self.assertEqual(state, "running")
                    mock_state.assert_called_once_with(f"{project_id}-cli-1")
