import subprocess
import unittest
import unittest.mock
from contextlib import redirect_stdout
from io import StringIO

import yaml

from luskctl.lib.containers.runtime import get_container_state, get_task_container_state
from luskctl.lib.containers.task_runners import task_restart
from luskctl.lib.containers.tasks import task_new, task_status, task_stop
from test_utils import mock_git_config, project_env


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
        project_id = "proj_stop"
        with project_env(f"project:\n  id: {project_id}\n", project_id=project_id) as ctx:
            # Create a task and simulate it's running
            task_new(project_id)
            meta_dir = ctx.state_dir / "projects" / project_id / "tasks"
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
        project_id = "proj_stop2"
        with project_env(f"project:\n  id: {project_id}\n", project_id=project_id):
            with mock_git_config():
                with self.assertRaises(SystemExit) as ctx:
                    task_stop(project_id, "999")
                self.assertIn("Unknown task", str(ctx.exception))

    def test_task_restart_starts_exited_container(self) -> None:
        """task_restart uses 'podman start' for exited container."""
        project_id = "proj_restart"
        with project_env(f"project:\n  id: {project_id}\n", project_id=project_id) as ctx:
            # Create a task and simulate it's stopped
            task_new(project_id)
            meta_dir = ctx.state_dir / "projects" / project_id / "tasks"
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
        """task_restart stops then starts a running container."""
        project_id = "proj_restart2"
        with project_env(f"project:\n  id: {project_id}\n", project_id=project_id) as ctx:
            task_new(project_id)
            meta_dir = ctx.state_dir / "projects" / project_id / "tasks"
            meta_path = meta_dir / "1.yml"

            meta = yaml.safe_load(meta_path.read_text())
            meta["status"] = "running"
            meta["mode"] = "cli"
            meta_path.write_text(yaml.safe_dump(meta))

            cname = f"{project_id}-cli-1"

            # Mock container is running, then running again after restart
            with (
                mock_git_config(),
                unittest.mock.patch(
                    "luskctl.lib.containers.task_runners.get_container_state",
                    side_effect=["running", "running"],
                ),
                unittest.mock.patch(
                    "luskctl.lib.containers.task_runners.subprocess.run"
                ) as run_mock,
            ):
                run_mock.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                output = StringIO()
                with redirect_stdout(output):
                    task_restart(project_id, "1")

                # Verify podman stop then start were called
                self.assertEqual(run_mock.call_count, 2)
                stop_args = run_mock.call_args_list[0][0][0]
                start_args = run_mock.call_args_list[1][0][0]
                self.assertEqual(stop_args, ["podman", "stop", cname])
                self.assertEqual(start_args, ["podman", "start", cname])

                # Verify message indicates restarted
                self.assertIn("Restarted", output.getvalue())

            # Verify metadata status is 'running'
            meta = yaml.safe_load(meta_path.read_text())
            self.assertEqual(meta["status"], "running")

    def test_task_status_shows_mismatch(self) -> None:
        """task_status detects metadata vs container state mismatch."""
        project_id = "proj_status"
        with project_env(f"project:\n  id: {project_id}\n", project_id=project_id) as ctx:
            task_new(project_id)
            meta_dir = ctx.state_dir / "projects" / project_id / "tasks"
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
        project_id = "proj_tui"
        with project_env(f"project:\n  id: {project_id}\n", project_id=project_id):
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
