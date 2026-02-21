import os
import subprocess
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import yaml

from luskctl.containers.environment import _apply_web_env_overrides, _build_task_env_and_volumes
from luskctl.containers.runtime import _get_container_state, get_task_container_state
from luskctl.containers.tasks import (
    get_login_command,
    get_workspace_git_diff,
    task_delete,
    task_login,
    task_new,
    task_restart,
    task_run_cli,
    task_run_web,
    task_status,
    task_stop,
)
from luskctl.core.projects import load_project
from luskctl.tui.clipboard import (
    copy_to_clipboard,
    copy_to_clipboard_detailed,
    get_clipboard_helper_status,
)
from test_utils import mock_git_config, parse_meta_value, write_project


def _assert_volume_mount(volumes: list[str], expected_base: str, expected_suffix: str) -> None:
    """Assert that a volume mount exists with the correct SELinux suffix.

    Args:
        volumes: List of volume mount strings
        expected_base: The base mount string without SELinux suffix
        expected_suffix: The expected SELinux suffix (e.g., ":Z" or ":z")
    """
    expected_full = f"{expected_base}{expected_suffix}"

    # Check if the expected mount exists (may have additional options like ,ro)
    found = False
    for volume in volumes:
        if volume.startswith(expected_full):
            # Check if it's either exactly the expected full string, or has additional options
            remaining = volume[len(expected_full) :]
            if not remaining or remaining.startswith(","):
                found = True
                break

    if not found:
        # For debugging, show what we actually got
        similar_mounts = [v for v in volumes if expected_base in v]
        raise AssertionError(
            f"Expected volume mount '{expected_full}' (or with additional options) not found in volumes. "
            f"Similar mounts found: {similar_mounts}"
        )


class TaskTests(unittest.TestCase):
    def test_copy_to_clipboard_no_helpers_provides_install_hint(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}):
            with unittest.mock.patch("luskctl.tui.clipboard.shutil.which", return_value=None):
                result = copy_to_clipboard_detailed("hello")
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.hint)
        self.assertIn("xclip", result.hint or "")

    def test_copy_to_clipboard_uses_xclip_when_available(self) -> None:
        def which_side_effect(name: str):
            return "/usr/bin/xclip" if name == "xclip" else None

        with unittest.mock.patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}):
            with unittest.mock.patch(
                "luskctl.tui.clipboard.shutil.which", side_effect=which_side_effect
            ):
                with unittest.mock.patch("luskctl.tui.clipboard.subprocess.run") as run_mock:
                    run_mock.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                    result = copy_to_clipboard_detailed("hello")

        self.assertTrue(result.ok)
        self.assertEqual(result.method, "xclip")
        run_mock.assert_called()

    def test_task_new_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj8"
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
                returned_id = task_new(project_id)
                self.assertEqual(returned_id, "1")
                meta_dir = state_dir / "projects" / project_id / "tasks"
                meta_path = meta_dir / "1.yml"
                self.assertTrue(meta_path.is_file())

                meta_text = meta_path.read_text(encoding="utf-8")
                self.assertEqual(parse_meta_value(meta_text, "task_id"), "1")
                workspace = Path(parse_meta_value(meta_text, "workspace") or "")
                self.assertTrue(workspace.is_dir())

                # Verify second task returns incremented ID
                second_id = task_new(project_id)
                self.assertEqual(second_id, "2")

                with unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as run_mock:
                    run_mock.return_value.returncode = 0
                    task_delete(project_id, "1")

                self.assertFalse(meta_path.exists())
                self.assertFalse(workspace.exists())

    def test_task_new_creates_marker_file(self) -> None:
        """Verify that task_new() creates the .new-task-marker file.

        The marker file signals to init-ssh-and-repo.sh that this is a fresh
        task and the workspace should be reset to the latest remote HEAD.
        See the docstring in task_new() for the full protocol description.
        """
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_marker"
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

                # Verify marker file exists in the workspace subdirectory
                workspace_dir = state_dir / "tasks" / project_id / "1" / "workspace"
                marker_path = workspace_dir / ".new-task-marker"
                self.assertTrue(
                    marker_path.is_file(), "Marker file should be created by task_new()"
                )

                # Verify marker content explains its purpose
                marker_content = marker_path.read_text(encoding="utf-8")
                self.assertIn("reset to the latest remote HEAD", marker_content)

    def test_build_task_env_gatekeeping(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            envs_dir = base / "envs"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj9"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\n  security_class: gatekeeping\ngit:\n  default_branch: main\n""".lstrip(),
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
            ):
                gate_dir = state_dir / "gate" / f"{project_id}.git"
                gate_dir.mkdir(parents=True, exist_ok=True)

                env, volumes = _build_task_env_and_volumes(
                    project=load_project(project_id),
                    task_id="7",
                )

                self.assertEqual(env["CODE_REPO"], "file:///git-gate/gate.git")
                _assert_volume_mount(volumes, f"{gate_dir}:/git-gate/gate.git", ":z")
                # Verify SSH is NOT mounted by default in gatekeeping mode
                ssh_mounts = [v for v in volumes if "/home/dev/.ssh" in v]
                self.assertEqual(ssh_mounts, [])

    def test_build_task_env_gatekeeping_with_ssh(self) -> None:
        """Gatekeeping mode with mount_in_gatekeeping enabled should mount SSH."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            envs_dir = base / "envs"
            ssh_dir = base / "ssh"
            config_root.mkdir(parents=True, exist_ok=True)
            ssh_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj_gatekeeping_ssh"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\n  security_class: gatekeeping\ngit:\n  default_branch: main\nssh:\n  host_dir: {ssh_dir}\n  mount_in_gatekeeping: true\n""".lstrip(),
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
            ):
                gate_dir = state_dir / "gate" / f"{project_id}.git"
                gate_dir.mkdir(parents=True, exist_ok=True)

                env, volumes = _build_task_env_and_volumes(
                    project=load_project(project_id),
                    task_id="9",
                )

                # Verify gatekeeping behavior: CODE_REPO is file-based gate
                self.assertEqual(env["CODE_REPO"], "file:///git-gate/gate.git")
                _assert_volume_mount(volumes, f"{gate_dir}:/git-gate/gate.git", ":z")
                # Verify SSH IS mounted when mount_in_gatekeeping is true
                _assert_volume_mount(volumes, f"{ssh_dir}:/home/dev/.ssh", ":z")

    def test_build_task_env_online(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            envs_dir = base / "envs"
            ssh_dir = base / "ssh"
            config_root.mkdir(parents=True, exist_ok=True)
            ssh_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj10"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\n  security_class: online\ngit:\n  upstream_url: https://example.com/repo.git\n  default_branch: main\nssh:\n  host_dir: {ssh_dir}\n  mount_in_online: true\n""".lstrip(),
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
            ):
                gate_dir = state_dir / "gate" / f"{project_id}.git"
                gate_dir.mkdir(parents=True, exist_ok=True)

                env, volumes = _build_task_env_and_volumes(load_project(project_id), task_id="8")
                self.assertEqual(env["CODE_REPO"], "https://example.com/repo.git")
                self.assertEqual(env["GIT_BRANCH"], "main")
                _assert_volume_mount(volumes, f"{gate_dir}:/git-gate/gate.git", ":z")
                _assert_volume_mount(volumes, f"{ssh_dir}:/home/dev/.ssh", ":z")

    def test_apply_ui_env_overrides_passthrough(self) -> None:
        base_env = {"EXISTING": "1", "CLAUDE_API_KEY": "override"}
        # Host env uses LUSKUI_* prefix for passthrough to containers
        with unittest.mock.patch.dict(
            os.environ,
            {
                "LUSKUI_TOKEN": "token-123",
                "LUSKUI_MISTRAL_API_KEY": "mistral-xyz",
                "ANTHROPIC_API_KEY": "anthropic-456",
                "CLAUDE_API_KEY": "from-env",
                "MISTRAL_API_KEY": "mistral-456",
            },
            clear=True,
        ):
            merged = _apply_web_env_overrides(base_env, "CLAUDE")

        # Container receives LUSKUI_* passthrough
        self.assertEqual(merged["LUSKUI_BACKEND"], "claude")
        self.assertEqual(merged["LUSKUI_TOKEN"], "token-123")
        self.assertEqual(merged["LUSKUI_MISTRAL_API_KEY"], "mistral-xyz")
        self.assertEqual(merged["ANTHROPIC_API_KEY"], "anthropic-456")
        self.assertEqual(merged["CLAUDE_API_KEY"], "override")
        self.assertEqual(merged["MISTRAL_API_KEY"], "mistral-456")

    def test_task_run_web_passes_passthrough_env(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            envs_dir = base / "envs"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_ui_env"
            write_project(
                config_root,
                project_id,
                f"project:\n  id: {project_id}\n",
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            # Host env uses LUSKUI_* prefix for passthrough to containers
            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                    "LUSKUI_TOKEN": "token-xyz",
                    "LUSKUI_MISTRAL_API_KEY": "mistral-xyz",
                    "ANTHROPIC_API_KEY": "anthropic-abc",
                    "MISTRAL_API_KEY": "mistral-abc",
                },
                clear=True,
            ):
                task_new(project_id)
                with (
                    mock_git_config(),
                    unittest.mock.patch(
                        "luskctl.containers.tasks._stream_initial_logs",
                        return_value=True,
                    ),
                    unittest.mock.patch(
                        "luskctl.containers.tasks._get_container_state",
                        return_value=None,  # No existing container
                    ),
                    unittest.mock.patch(
                        "luskctl.containers.tasks._is_container_running",
                        return_value=True,
                    ),
                    unittest.mock.patch(
                        "luskctl.containers.tasks._assign_web_port",
                        return_value=7788,
                    ),
                    unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as run_mock,
                ):
                    run_mock.return_value = subprocess.CompletedProcess([], 0)
                    task_run_web(project_id, "1", backend="CLAUDE")

                cmd = run_mock.call_args[0][0]
                env_entries = {cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-e"}

                # Container receives LUSKUI_* passthrough
                self.assertIn("LUSKUI_BACKEND=claude", env_entries)
                self.assertIn("LUSKUI_TOKEN=token-xyz", env_entries)
                self.assertIn("LUSKUI_MISTRAL_API_KEY=mistral-xyz", env_entries)
                self.assertIn("ANTHROPIC_API_KEY=anthropic-abc", env_entries)
                self.assertIn("MISTRAL_API_KEY=mistral-abc", env_entries)

    def test_task_run_cli_colors_login_lines_when_tty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            envs_dir = base / "envs"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_cli_color"
            write_project(
                config_root,
                project_id,
                f"project:\n  id: {project_id}\n",
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
                clear=True,
            ):
                task_new(project_id)
                with (
                    mock_git_config(),
                    unittest.mock.patch(
                        "luskctl.containers.tasks._stream_initial_logs",
                        return_value=True,
                    ),
                    unittest.mock.patch(
                        "luskctl.containers.tasks._get_container_state",
                        return_value=None,  # No existing container
                    ),
                    unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as run_mock,
                    unittest.mock.patch(
                        "luskctl.containers.tasks._supports_color",
                        return_value=True,
                    ),
                ):
                    run_mock.return_value = subprocess.CompletedProcess([], 0)
                    buffer = StringIO()
                    with redirect_stdout(buffer):
                        task_run_cli(project_id, "1")

                output = buffer.getvalue()
                expected_name = f"\x1b[32m{project_id}-cli-1\x1b[0m"
                expected_enter = f"\x1b[34mpodman exec -it {project_id}-cli-1 bash\x1b[0m"
                expected_stop = f"\x1b[31mpodman stop {project_id}-cli-1\x1b[0m"
                self.assertIn(expected_name, output)
                self.assertIn(expected_enter, output)
                self.assertIn(expected_stop, output)

    def test_task_run_web_colors_url_and_stop_when_tty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            envs_dir = base / "envs"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_web_color"
            write_project(
                config_root,
                project_id,
                f"project:\n  id: {project_id}\n",
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
                clear=True,
            ):
                task_new(project_id)
                with (
                    mock_git_config(),
                    unittest.mock.patch(
                        "luskctl.containers.tasks._stream_initial_logs",
                        return_value=True,
                    ),
                    unittest.mock.patch(
                        "luskctl.containers.tasks._get_container_state",
                        return_value=None,  # No existing container
                    ),
                    unittest.mock.patch(
                        "luskctl.containers.tasks._is_container_running",
                        return_value=True,
                    ),
                    unittest.mock.patch(
                        "luskctl.containers.tasks._assign_web_port",
                        return_value=7788,
                    ),
                    unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as run_mock,
                    unittest.mock.patch(
                        "luskctl.containers.tasks._supports_color",
                        return_value=True,
                    ),
                ):
                    run_mock.return_value = subprocess.CompletedProcess([], 0)
                    buffer = StringIO()
                    with redirect_stdout(buffer):
                        task_run_web(project_id, "1")

                output = buffer.getvalue()
                expected_name = f"\x1b[32m{project_id}-web-1\x1b[0m"
                expected_url = "\x1b[34mhttp://127.0.0.1:7788/\x1b[0m"
                expected_logs = f"\x1b[33mpodman logs -f {project_id}-web-1\x1b[0m"
                expected_stop = f"\x1b[31mpodman stop {project_id}-web-1\x1b[0m"
                self.assertIn(expected_name, output)
                self.assertIn(expected_url, output)
                self.assertIn(expected_logs, output)
                self.assertIn(expected_stop, output)

    def test_task_run_cli_already_running(self) -> None:
        """task_run_cli prints message and exits when container is already running."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_cli_running"
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
                with (
                    mock_git_config(),
                    unittest.mock.patch(
                        "luskctl.containers.tasks._get_container_state", return_value="running"
                    ),
                    unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as run_mock,
                ):
                    buffer = StringIO()
                    with redirect_stdout(buffer):
                        task_run_cli(project_id, "1")

                    # Verify no podman run was called
                    run_mock.assert_not_called()

                    # Verify message indicates already running
                    output = buffer.getvalue()
                    self.assertIn("already running", output)

    def test_task_run_cli_starts_stopped_container(self) -> None:
        """task_run_cli uses 'podman start' for stopped container."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_cli_stopped"
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

                # Simulate task was previously run
                meta = yaml.safe_load(meta_path.read_text())
                meta["mode"] = "cli"
                meta["status"] = "stopped"
                meta_path.write_text(yaml.safe_dump(meta))

                with (
                    mock_git_config(),
                    unittest.mock.patch(
                        "luskctl.containers.tasks._get_container_state", return_value="exited"
                    ),
                    unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as run_mock,
                ):
                    run_mock.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                    buffer = StringIO()
                    with redirect_stdout(buffer):
                        task_run_cli(project_id, "1")

                    # Verify podman start was called
                    run_mock.assert_called_once()
                    call_args = run_mock.call_args[0][0]
                    self.assertEqual(call_args[:2], ["podman", "start"])

                    # Verify metadata status is now 'running'
                    meta = yaml.safe_load(meta_path.read_text())
                    self.assertEqual(meta["status"], "running")
                    self.assertEqual(meta["mode"], "cli")

    def test_task_run_web_already_running(self) -> None:
        """task_run_web prints message and exits when container is already running."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            envs_dir = base / "envs"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_web_running"
            write_project(
                config_root,
                project_id,
                f"project:\n  id: {project_id}\n",
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
                clear=True,
            ):
                task_new(project_id)
                meta_dir = state_dir / "projects" / project_id / "tasks"
                meta_path = meta_dir / "1.yml"

                # Simulate task was previously run
                meta = yaml.safe_load(meta_path.read_text())
                meta["mode"] = "web"
                meta["web_port"] = 7860
                meta_path.write_text(yaml.safe_dump(meta))

                with (
                    mock_git_config(),
                    unittest.mock.patch(
                        "luskctl.containers.tasks._get_container_state", return_value="running"
                    ),
                    unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as run_mock,
                ):
                    buffer = StringIO()
                    with redirect_stdout(buffer):
                        task_run_web(project_id, "1")

                    # Verify no podman run was called
                    run_mock.assert_not_called()

                    # Verify message indicates already running
                    output = buffer.getvalue()
                    self.assertIn("already running", output)

    def test_task_run_web_starts_stopped_container(self) -> None:
        """task_run_web uses 'podman start' for stopped container."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            envs_dir = base / "envs"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_web_stopped"
            write_project(
                config_root,
                project_id,
                f"project:\n  id: {project_id}\n",
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
                clear=True,
            ):
                task_new(project_id)
                meta_dir = state_dir / "projects" / project_id / "tasks"
                meta_path = meta_dir / "1.yml"

                # Simulate task was previously run
                meta = yaml.safe_load(meta_path.read_text())
                meta["mode"] = "web"
                meta["web_port"] = 7860
                meta["status"] = "stopped"
                meta_path.write_text(yaml.safe_dump(meta))

                with (
                    mock_git_config(),
                    unittest.mock.patch(
                        "luskctl.containers.tasks._get_container_state", return_value="exited"
                    ),
                    unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as run_mock,
                ):
                    run_mock.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                    buffer = StringIO()
                    with redirect_stdout(buffer):
                        task_run_web(project_id, "1")

                    # Verify podman start was called
                    run_mock.assert_called_once()
                    call_args = run_mock.call_args[0][0]
                    self.assertEqual(call_args[:2], ["podman", "start"])

                    # Verify metadata status is now 'running'
                    meta = yaml.safe_load(meta_path.read_text())
                    self.assertEqual(meta["status"], "running")

    def test_get_workspace_git_diff_no_workspace(self) -> None:
        """Test get_workspace_git_diff returns None when workspace doesn't exist."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_diff_1"
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
                # Try to get diff for non-existent task
                result = get_workspace_git_diff(project_id, "999")
                self.assertIsNone(result)

    def test_get_workspace_git_diff_no_git_repo(self) -> None:
        """Test get_workspace_git_diff returns None when workspace is not a git repo."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_diff_2"
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
                # Workspace exists but .git directory doesn't
                result = get_workspace_git_diff(project_id, "1")
                self.assertIsNone(result)

    def test_get_workspace_git_diff_clean_working_tree(self) -> None:
        """Test get_workspace_git_diff returns empty string for clean working tree."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_diff_3"
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

                # Mock subprocess.run to simulate clean git repository
                with unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as run_mock:
                    mock_result = unittest.mock.Mock()
                    mock_result.returncode = 0
                    mock_result.stdout = ""
                    run_mock.return_value = mock_result

                    # Also need to mock .git existence check
                    workspace_dir = state_dir / "tasks" / project_id / "1" / "workspace"
                    git_dir = workspace_dir / ".git"
                    git_dir.mkdir(parents=True, exist_ok=True)

                    result = get_workspace_git_diff(project_id, "1")
                    self.assertEqual(result, "")

    def test_get_workspace_git_diff_with_changes(self) -> None:
        """Test get_workspace_git_diff returns diff output when there are changes."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_diff_4"
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

                expected_diff = "diff --git a/file.txt b/file.txt\n+new line\n"

                with (
                    mock_git_config(),
                    unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as run_mock,
                ):
                    mock_result = unittest.mock.Mock()
                    mock_result.returncode = 0
                    mock_result.stdout = expected_diff
                    run_mock.return_value = mock_result

                    workspace_dir = state_dir / "tasks" / project_id / "1" / "workspace"
                    git_dir = workspace_dir / ".git"
                    git_dir.mkdir(parents=True, exist_ok=True)

                    result = get_workspace_git_diff(project_id, "1", "HEAD")
                    self.assertEqual(result, expected_diff)

                    # Verify git diff command was called correctly
                    run_mock.assert_called_once()
                    call_args = run_mock.call_args[0][0]
                    self.assertEqual(call_args[0], "git")
                    self.assertEqual(call_args[1], "-C")
                    self.assertEqual(call_args[3], "diff")
                    self.assertEqual(call_args[4], "HEAD")

    def test_get_workspace_git_diff_prev_commit(self) -> None:
        """Test get_workspace_git_diff with PREV option."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_diff_5"
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

                expected_diff = "diff --git a/file.txt b/file.txt\n+previous commit change\n"

                with (
                    mock_git_config(),
                    unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as run_mock,
                ):
                    mock_result = unittest.mock.Mock()
                    mock_result.returncode = 0
                    mock_result.stdout = expected_diff
                    run_mock.return_value = mock_result

                    workspace_dir = state_dir / "tasks" / project_id / "1" / "workspace"
                    git_dir = workspace_dir / ".git"
                    git_dir.mkdir(parents=True, exist_ok=True)

                    result = get_workspace_git_diff(project_id, "1", "PREV")
                    self.assertEqual(result, expected_diff)

                    # Verify git command was called with HEAD~1
                    run_mock.assert_called_once()
                    call_args = run_mock.call_args[0][0]
                    self.assertEqual(call_args[0], "git")
                    self.assertEqual(call_args[1], "-C")
                    self.assertEqual(call_args[3], "diff")
                    self.assertEqual(call_args[4], "HEAD~1")
                    self.assertEqual(call_args[5], "HEAD")

    def test_get_workspace_git_diff_error(self) -> None:
        """Test get_workspace_git_diff returns None when git command fails."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_diff_6"
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

                with unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as run_mock:
                    # Simulate git command failure
                    mock_result = unittest.mock.Mock()
                    mock_result.returncode = 1
                    run_mock.return_value = mock_result

                    workspace_dir = state_dir / "tasks" / project_id / "1" / "workspace"
                    git_dir = workspace_dir / ".git"
                    git_dir.mkdir(parents=True, exist_ok=True)

                    result = get_workspace_git_diff(project_id, "1")
                    self.assertIsNone(result)

    def test_copy_to_clipboard_empty_text(self) -> None:
        """Test copy_to_clipboard returns False for empty text."""
        result = copy_to_clipboard("")
        self.assertFalse(result)

    def test_copy_to_clipboard_success_wl_copy(self) -> None:
        """Test copy_to_clipboard succeeds with wl-copy."""
        with unittest.mock.patch.dict(
            os.environ, {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}
        ):
            with unittest.mock.patch(
                "luskctl.tui.clipboard.shutil.which", return_value="/usr/bin/wl-copy"
            ):
                with unittest.mock.patch("luskctl.tui.clipboard.subprocess.run") as run_mock:
                    run_mock.return_value = subprocess.CompletedProcess(args=[], returncode=0)

                    result = copy_to_clipboard("test content")
                    self.assertTrue(result)

                    run_mock.assert_called_once()
                    args, kwargs = run_mock.call_args
                    self.assertEqual(args[0][0], "wl-copy")
                    self.assertEqual(kwargs["input"], "test content")
                    self.assertTrue(kwargs["check"])
                    self.assertTrue(kwargs["text"])
                    self.assertTrue(kwargs["capture_output"])

    def test_copy_to_clipboard_fallback_to_xclip(self) -> None:
        """Test copy_to_clipboard uses xclip on X11 when available."""
        # Ensure Wayland environment variables are not set to force X11 detection
        env = {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0", "WAYLAND_DISPLAY": ""}

        with unittest.mock.patch.dict(os.environ, env, clear=False):
            with unittest.mock.patch(
                "luskctl.tui.clipboard.shutil.which", return_value="/usr/bin/xclip"
            ):
                with unittest.mock.patch("luskctl.tui.clipboard.subprocess.run") as run_mock:
                    run_mock.return_value = subprocess.CompletedProcess(args=[], returncode=0)

                    result = copy_to_clipboard("test content")
                    self.assertTrue(result)

                    run_mock.assert_called_once()
                    args, _kwargs = run_mock.call_args
                    self.assertEqual(args[0][0], "xclip")

    def test_copy_to_clipboard_fallback_to_pbcopy(self) -> None:
        """Test copy_to_clipboard_detailed uses pbcopy on macOS and sets method field."""
        with unittest.mock.patch("luskctl.tui.clipboard.sys.platform", "darwin"):
            with unittest.mock.patch(
                "luskctl.tui.clipboard.shutil.which", return_value="/usr/bin/pbcopy"
            ):
                with unittest.mock.patch("luskctl.tui.clipboard.subprocess.run") as run_mock:
                    run_mock.return_value = subprocess.CompletedProcess(args=[], returncode=0)

                    result = copy_to_clipboard_detailed("test content")
                    self.assertTrue(result.ok)
                    self.assertEqual(result.method, "pbcopy")

                    run_mock.assert_called_once()
                    args, _kwargs = run_mock.call_args
                    self.assertEqual(args[0][0], "pbcopy")

    def test_copy_to_clipboard_all_fail(self) -> None:
        """Test copy_to_clipboard_detailed returns proper error when all clipboard utilities fail."""
        with unittest.mock.patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}):

            def which_side_effect(name: str):
                if name in ("xclip", "xsel"):
                    return f"/usr/bin/{name}"
                return None

            with unittest.mock.patch(
                "luskctl.tui.clipboard.shutil.which", side_effect=which_side_effect
            ):
                with unittest.mock.patch("luskctl.tui.clipboard.subprocess.run") as run_mock:
                    run_mock.side_effect = subprocess.CalledProcessError(
                        1, ["xclip"], stderr="boom"
                    )

                    result = copy_to_clipboard_detailed("test content")
                    self.assertFalse(result.ok)
                    self.assertIsNotNone(result.error)
                    self.assertIn("failed", result.error)

                    self.assertEqual(run_mock.call_count, 2)

    def test_get_clipboard_helper_status_with_available_helpers(self) -> None:
        """Test get_clipboard_helper_status returns available helpers on macOS."""
        with unittest.mock.patch("luskctl.tui.clipboard.sys.platform", "darwin"):
            with unittest.mock.patch(
                "luskctl.tui.clipboard.shutil.which", return_value="/usr/bin/pbcopy"
            ):
                status = get_clipboard_helper_status()
                self.assertTrue(status.available)
                self.assertIn("pbcopy", status.available)
                self.assertIsNone(status.hint)

    def test_get_clipboard_helper_status_no_helpers_wayland(self) -> None:
        """Test get_clipboard_helper_status returns hint for Wayland when no helpers available."""
        with unittest.mock.patch.dict(
            os.environ, {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}
        ):
            with unittest.mock.patch("luskctl.tui.clipboard.shutil.which", return_value=None):
                status = get_clipboard_helper_status()
                self.assertEqual(status.available, ())
                self.assertIsNotNone(status.hint)
                self.assertIn("wl-clipboard", status.hint)

    def test_get_clipboard_helper_status_no_helpers_x11(self) -> None:
        """Test get_clipboard_helper_status returns hint for X11 when no helpers available."""
        with unittest.mock.patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}):
            with unittest.mock.patch("luskctl.tui.clipboard.shutil.which", return_value=None):
                status = get_clipboard_helper_status()
                self.assertEqual(status.available, ())
                self.assertIsNotNone(status.hint)
                self.assertIn("xclip", status.hint)

    def test_build_task_env_gatekeeping_expose_external_remote_enabled(self) -> None:
        """Test expose_external_remote=true with upstream_url sets EXTERNAL_REMOTE_URL."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            envs_dir = base / "envs"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_external_remote_enabled"
            upstream_url = "https://github.com/example/repo.git"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\n  security_class: gatekeeping\ngit:\n  upstream_url: {upstream_url}\n  default_branch: main\ngatekeeping:\n  expose_external_remote: true\n""".lstrip(),
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
            ):
                gate_dir = state_dir / "gate" / f"{project_id}.git"
                gate_dir.mkdir(parents=True, exist_ok=True)

                env, volumes = _build_task_env_and_volumes(
                    project=load_project(project_id),
                    task_id="10",
                )

                # Verify EXTERNAL_REMOTE_URL is set when expose_external_remote is enabled
                self.assertEqual(env["EXTERNAL_REMOTE_URL"], upstream_url)
                # Verify gatekeeping mode settings are still correct
                self.assertEqual(env["CODE_REPO"], "file:///git-gate/gate.git")
                _assert_volume_mount(volumes, f"{gate_dir}:/git-gate/gate.git", ":z")

    def test_build_task_env_gatekeeping_expose_external_remote_disabled(self) -> None:
        """Test expose_external_remote=false does not set EXTERNAL_REMOTE_URL."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            envs_dir = base / "envs"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_external_remote_disabled"
            upstream_url = "https://github.com/example/repo.git"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\n  security_class: gatekeeping\ngit:\n  upstream_url: {upstream_url}\n  default_branch: main\ngatekeeping:\n  expose_external_remote: false\n""".lstrip(),
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
            ):
                gate_dir = state_dir / "gate" / f"{project_id}.git"
                gate_dir.mkdir(parents=True, exist_ok=True)

                env, volumes = _build_task_env_and_volumes(
                    project=load_project(project_id),
                    task_id="11",
                )

                # Verify EXTERNAL_REMOTE_URL is NOT set when expose_external_remote is false
                self.assertNotIn("EXTERNAL_REMOTE_URL", env)
                # Verify gatekeeping mode settings are still correct
                self.assertEqual(env["CODE_REPO"], "file:///git-gate/gate.git")
                _assert_volume_mount(volumes, f"{gate_dir}:/git-gate/gate.git", ":z")

    def test_build_task_env_gatekeeping_expose_external_remote_no_upstream(self) -> None:
        """Test expose_external_remote=true without upstream_url does not set EXTERNAL_REMOTE_URL."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            envs_dir = base / "envs"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_external_remote_no_upstream"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\n  security_class: gatekeeping\ngit:\n  default_branch: main\ngatekeeping:\n  expose_external_remote: true\n""".lstrip(),
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                    "LUSKCTL_CONFIG_FILE": str(config_file),
                },
            ):
                gate_dir = state_dir / "gate" / f"{project_id}.git"
                gate_dir.mkdir(parents=True, exist_ok=True)

                env, volumes = _build_task_env_and_volumes(
                    project=load_project(project_id),
                    task_id="12",
                )

                # Verify EXTERNAL_REMOTE_URL is NOT set when upstream_url is missing
                self.assertNotIn("EXTERNAL_REMOTE_URL", env)
                # Verify gatekeeping mode settings are still correct
                self.assertEqual(env["CODE_REPO"], "file:///git-gate/gate.git")
                _assert_volume_mount(volumes, f"{gate_dir}:/git-gate/gate.git", ":z")


class ContainerLifecycleTests(unittest.TestCase):
    """Tests for container lifecycle management: stop, restart, status."""

    def test_get_container_state_running(self) -> None:
        """_get_container_state returns 'running' for running container."""
        with unittest.mock.patch(
            "luskctl.containers.runtime.subprocess.check_output", return_value="running\n"
        ):
            state = _get_container_state("test-container")
            self.assertEqual(state, "running")

    def test_get_container_state_exited(self) -> None:
        """_get_container_state returns 'exited' for stopped container."""
        with unittest.mock.patch(
            "luskctl.containers.runtime.subprocess.check_output", return_value="exited\n"
        ):
            state = _get_container_state("test-container")
            self.assertEqual(state, "exited")

    def test_get_container_state_not_found(self) -> None:
        """_get_container_state returns None if container doesn't exist."""
        with unittest.mock.patch(
            "luskctl.containers.runtime.subprocess.check_output",
            side_effect=subprocess.CalledProcessError(1, "podman"),
        ):
            state = _get_container_state("test-container")
            self.assertIsNone(state)

    def test_get_container_state_podman_not_found(self) -> None:
        """_get_container_state returns None if podman is not installed."""
        with unittest.mock.patch(
            "luskctl.containers.runtime.subprocess.check_output",
            side_effect=FileNotFoundError("podman"),
        ):
            state = _get_container_state("test-container")
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
                        "luskctl.containers.tasks._get_container_state", return_value="running"
                    ),
                    unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as run_mock,
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
                        "luskctl.containers.tasks._get_container_state", return_value="exited"
                    ),
                    unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as run_mock,
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
                        "luskctl.containers.tasks._get_container_state", return_value="running"
                    ),
                    unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as run_mock,
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
                        "luskctl.containers.tasks._get_container_state", return_value="exited"
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
                        "luskctl.containers.runtime._get_container_state", return_value="running"
                    ) as mock_state,
                ):
                    state = get_task_container_state(project_id, "1", "cli")
                    self.assertEqual(state, "running")
                    mock_state.assert_called_once_with(f"{project_id}-cli-1")


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
                    "luskctl.containers.tasks._get_container_state", return_value=None
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
                    "luskctl.containers.tasks._get_container_state", return_value="exited"
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
                        "luskctl.containers.tasks._get_container_state",
                        return_value="running",
                    ),
                    unittest.mock.patch("luskctl.containers.tasks.os.execvp") as mock_exec,
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
                    "luskctl.containers.tasks._get_container_state",
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
                    "luskctl.containers.tasks._get_container_state",
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
                        "luskctl.containers.tasks._get_container_state",
                        return_value="running",
                    ),
                    mock_git_config(),
                    unittest.mock.patch("luskctl.containers.tasks.subprocess.run") as mock_run,
                ):
                    cmd = get_login_command("proj_login_cfg", "1")

                    # Should still return the tmux command
                    self.assertEqual(cmd[3], "proj_login_cfg-cli-1")
                    self.assertIn("tmux", cmd)

                    # No podman exec/cp calls — config injection is via mount
                    mock_run.assert_not_called()
