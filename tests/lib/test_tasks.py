from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from codexctl.lib.projects import load_project
from codexctl.lib.tasks import (
    _apply_ui_env_overrides,
    _build_task_env_and_volumes,
    copy_to_clipboard,
    get_workspace_git_diff,
    task_delete,
    task_new,
    task_run_ui,
)
from test_utils import parse_meta_value, write_project


class TaskTests(unittest.TestCase):
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
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                task_new(project_id)
                meta_dir = state_dir / "projects" / project_id / "tasks"
                meta_path = meta_dir / "1.yml"
                self.assertTrue(meta_path.is_file())

                meta_text = meta_path.read_text(encoding="utf-8")
                self.assertEqual(parse_meta_value(meta_text, "task_id"), "1")
                workspace = Path(parse_meta_value(meta_text, "workspace") or "")
                self.assertTrue(workspace.is_dir())

                with unittest.mock.patch("codexctl.lib.tasks.subprocess.run") as run_mock:
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
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                task_new(project_id)

                # Verify marker file exists in the workspace subdirectory
                workspace_dir = state_dir / "tasks" / project_id / "1" / "workspace"
                marker_path = workspace_dir / ".new-task-marker"
                self.assertTrue(marker_path.is_file(), "Marker file should be created by task_new()")

                # Verify marker content explains its purpose
                marker_content = marker_path.read_text(encoding="utf-8")
                self.assertIn("reset to the latest remote HEAD", marker_content)

    def test_build_task_env_gatekept(self) -> None:
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
                f"""\nproject:\n  id: {project_id}\n  security_class: gatekept\ngit:\n  default_branch: main\n""".lstrip(),
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                    "CODEXCTL_CONFIG_FILE": str(config_file),
                },
            ):
                cache_dir = state_dir / "cache" / f"{project_id}.git"
                cache_dir.mkdir(parents=True, exist_ok=True)

                env, volumes = _build_task_env_and_volumes(
                    project=load_project(project_id),
                    task_id="7",
                )

                self.assertEqual(env["CODE_REPO"], "file:///git-cache/cache.git")
                self.assertIn(f"{cache_dir}:/git-cache/cache.git:Z", volumes)
                # Verify SSH is NOT mounted by default in gatekept mode
                ssh_mounts = [v for v in volumes if "/home/dev/.ssh" in v]
                self.assertEqual(ssh_mounts, [])

    def test_build_task_env_gatekept_with_ssh(self) -> None:
        """Gatekept mode with mount_in_gatekeeping enabled should mount SSH."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            envs_dir = base / "envs"
            ssh_dir = base / "ssh"
            config_root.mkdir(parents=True, exist_ok=True)
            ssh_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj_gatekept_ssh"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\n  security_class: gatekept\ngit:\n  default_branch: main\nssh:\n  host_dir: {ssh_dir}\n  mount_in_gatekeeping: true\n""".lstrip(),
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                    "CODEXCTL_CONFIG_FILE": str(config_file),
                },
            ):
                cache_dir = state_dir / "cache" / f"{project_id}.git"
                cache_dir.mkdir(parents=True, exist_ok=True)

                env, volumes = _build_task_env_and_volumes(
                    project=load_project(project_id),
                    task_id="9",
                )

                # Verify gatekept behavior: CODE_REPO is file-based cache
                self.assertEqual(env["CODE_REPO"], "file:///git-cache/cache.git")
                self.assertIn(f"{cache_dir}:/git-cache/cache.git:Z", volumes)
                # Verify SSH IS mounted when mount_in_gatekeeping is true
                self.assertIn(f"{ssh_dir}:/home/dev/.ssh:Z", volumes)

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
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                    "CODEXCTL_CONFIG_FILE": str(config_file),
                },
            ):
                cache_dir = state_dir / "cache" / f"{project_id}.git"
                cache_dir.mkdir(parents=True, exist_ok=True)

                env, volumes = _build_task_env_and_volumes(load_project(project_id), task_id="8")
                self.assertEqual(env["CODE_REPO"], "https://example.com/repo.git")
                self.assertEqual(env["GIT_BRANCH"], "main")
                self.assertIn(f"{cache_dir}:/git-cache/cache.git:Z,ro", volumes)
                self.assertIn(f"{ssh_dir}:/home/dev/.ssh:Z", volumes)

    def test_apply_ui_env_overrides_passthrough(self) -> None:
        base_env = {"EXISTING": "1", "CLAUDE_API_KEY": "override"}
        with unittest.mock.patch.dict(
            os.environ,
            {
                "CODEXUI_TOKEN": "token-123",
                "CODEXUI_MISTRAL_API_KEY": "mistral-xyz",
                "ANTHROPIC_API_KEY": "anthropic-456",
                "CLAUDE_API_KEY": "from-env",
                "MISTRAL_API_KEY": "mistral-456",
            },
            clear=True,
        ):
            merged = _apply_ui_env_overrides(base_env, "CLAUDE")

        self.assertEqual(merged["CODEXUI_BACKEND"], "claude")
        self.assertEqual(merged["CODEXUI_TOKEN"], "token-123")
        self.assertEqual(merged["CODEXUI_MISTRAL_API_KEY"], "mistral-xyz")
        self.assertEqual(merged["ANTHROPIC_API_KEY"], "anthropic-456")
        self.assertEqual(merged["CLAUDE_API_KEY"], "override")
        self.assertEqual(merged["MISTRAL_API_KEY"], "mistral-456")

    def test_task_run_ui_passes_passthrough_env(self) -> None:
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

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                    "CODEXCTL_CONFIG_FILE": str(config_file),
                    "CODEXUI_TOKEN": "token-xyz",
                    "CODEXUI_MISTRAL_API_KEY": "mistral-xyz",
                    "ANTHROPIC_API_KEY": "anthropic-abc",
                    "MISTRAL_API_KEY": "mistral-abc",
                },
                clear=True,
            ):
                task_new(project_id)
                with unittest.mock.patch(
                    "codexctl.lib.tasks._stream_initial_logs",
                    return_value=True,
                ), unittest.mock.patch(
                    "codexctl.lib.tasks._is_container_running",
                    return_value=True,
                ), unittest.mock.patch(
                    "codexctl.lib.tasks._assign_ui_port",
                    return_value=7788,
                ), unittest.mock.patch(
                    "codexctl.lib.tasks.subprocess.run"
                ) as run_mock:
                    run_mock.return_value = subprocess.CompletedProcess([], 0)
                    task_run_ui(project_id, "1", backend="CLAUDE")

                cmd = run_mock.call_args[0][0]
                env_entries = {cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-e"}

                self.assertIn("CODEXUI_BACKEND=claude", env_entries)
                self.assertIn("CODEXUI_TOKEN=token-xyz", env_entries)
                self.assertIn("CODEXUI_MISTRAL_API_KEY=mistral-xyz", env_entries)
                self.assertIn("ANTHROPIC_API_KEY=anthropic-abc", env_entries)
                self.assertIn("MISTRAL_API_KEY=mistral-abc", env_entries)

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
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
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
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
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
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                task_new(project_id)

                # Mock subprocess.run to simulate clean git repository
                with unittest.mock.patch("codexctl.lib.tasks.subprocess.run") as run_mock:
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
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                task_new(project_id)

                expected_diff = "diff --git a/file.txt b/file.txt\n+new line\n"

                with unittest.mock.patch("codexctl.lib.tasks.subprocess.run") as run_mock:
                    mock_result = unittest.mock.Mock()
                    mock_result.returncode = 0
                    mock_result.stdout = expected_diff
                    run_mock.return_value = mock_result

                    workspace_dir = state_dir / "tasks" / project_id / "1" / "workspace"
                    git_dir = workspace_dir / ".git"
                    git_dir.mkdir(parents=True, exist_ok=True)

                    result = get_workspace_git_diff(project_id, "1", "HEAD")
                    self.assertEqual(result, expected_diff)

                    # Verify git command was called correctly
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
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                task_new(project_id)

                expected_diff = "diff --git a/file.txt b/file.txt\n+previous commit change\n"

                with unittest.mock.patch("codexctl.lib.tasks.subprocess.run") as run_mock:
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
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                task_new(project_id)

                with unittest.mock.patch("codexctl.lib.tasks.subprocess.run") as run_mock:
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
        with unittest.mock.patch("codexctl.lib.tasks.subprocess.run") as run_mock:
            mock_result = unittest.mock.Mock()
            mock_result.returncode = 0
            run_mock.return_value = mock_result

            result = copy_to_clipboard("test content")
            self.assertTrue(result)

            # Verify wl-copy was called with correct arguments
            run_mock.assert_called_once_with(
                ["wl-copy", "--type", "text/plain"],
                input="test content",
                check=True,
                text=True,
            )

    def test_copy_to_clipboard_fallback_to_xclip(self) -> None:
        """Test copy_to_clipboard falls back to xclip when wl-copy is not found."""
        with unittest.mock.patch("codexctl.lib.tasks.subprocess.run") as run_mock:
            # First call (wl-copy) raises FileNotFoundError
            # Second call (xclip) succeeds
            def side_effect(*args, **kwargs):
                if args[0][0] == "wl-copy":
                    raise FileNotFoundError()
                mock_result = unittest.mock.Mock()
                mock_result.returncode = 0
                return mock_result

            run_mock.side_effect = side_effect

            result = copy_to_clipboard("test content")
            self.assertTrue(result)

            # Verify xclip was called
            self.assertEqual(run_mock.call_count, 2)
            second_call = run_mock.call_args_list[1]
            self.assertEqual(second_call[0][0][0], "xclip")

    def test_copy_to_clipboard_fallback_to_pbcopy(self) -> None:
        """Test copy_to_clipboard falls back to pbcopy when wl-copy and xclip fail."""
        with unittest.mock.patch("codexctl.lib.tasks.subprocess.run") as run_mock:
            # First two calls fail, third succeeds
            def side_effect(*args, **kwargs):
                if args[0][0] in ["wl-copy", "xclip"]:
                    raise FileNotFoundError()
                mock_result = unittest.mock.Mock()
                mock_result.returncode = 0
                return mock_result

            run_mock.side_effect = side_effect

            result = copy_to_clipboard("test content")
            self.assertTrue(result)

            # Verify pbcopy was called
            self.assertEqual(run_mock.call_count, 3)
            third_call = run_mock.call_args_list[2]
            self.assertEqual(third_call[0][0][0], "pbcopy")

    def test_copy_to_clipboard_all_fail(self) -> None:
        """Test copy_to_clipboard returns False when all clipboard utilities fail."""
        with unittest.mock.patch("codexctl.lib.tasks.subprocess.run") as run_mock:
            # All clipboard utilities fail
            run_mock.side_effect = FileNotFoundError()

            result = copy_to_clipboard("test content")
            self.assertFalse(result)

            # Verify all three utilities were tried
            self.assertEqual(run_mock.call_count, 3)

    def test_build_task_env_gatekept_expose_external_remote_enabled(self) -> None:
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
                f"""\nproject:\n  id: {project_id}\n  security_class: gatekept\ngit:\n  upstream_url: {upstream_url}\n  default_branch: main\ngatekeeping:\n  expose_external_remote: true\n""".lstrip(),
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                    "CODEXCTL_CONFIG_FILE": str(config_file),
                },
            ):
                cache_dir = state_dir / "cache" / f"{project_id}.git"
                cache_dir.mkdir(parents=True, exist_ok=True)

                env, volumes = _build_task_env_and_volumes(
                    project=load_project(project_id),
                    task_id="10",
                )

                # Verify EXTERNAL_REMOTE_URL is set when expose_external_remote is enabled
                self.assertEqual(env["EXTERNAL_REMOTE_URL"], upstream_url)
                # Verify gatekeeping mode settings are still correct
                self.assertEqual(env["CODE_REPO"], "file:///git-cache/cache.git")
                self.assertIn(f"{cache_dir}:/git-cache/cache.git:Z", volumes)

    def test_build_task_env_gatekept_expose_external_remote_disabled(self) -> None:
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
                f"""\nproject:\n  id: {project_id}\n  security_class: gatekept\ngit:\n  upstream_url: {upstream_url}\n  default_branch: main\ngatekeeping:\n  expose_external_remote: false\n""".lstrip(),
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                    "CODEXCTL_CONFIG_FILE": str(config_file),
                },
            ):
                cache_dir = state_dir / "cache" / f"{project_id}.git"
                cache_dir.mkdir(parents=True, exist_ok=True)

                env, volumes = _build_task_env_and_volumes(
                    project=load_project(project_id),
                    task_id="11",
                )

                # Verify EXTERNAL_REMOTE_URL is NOT set when expose_external_remote is false
                self.assertNotIn("EXTERNAL_REMOTE_URL", env)
                # Verify gatekeeping mode settings are still correct
                self.assertEqual(env["CODE_REPO"], "file:///git-cache/cache.git")
                self.assertIn(f"{cache_dir}:/git-cache/cache.git:Z", volumes)

    def test_build_task_env_gatekept_expose_external_remote_no_upstream(self) -> None:
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
                f"""\nproject:\n  id: {project_id}\n  security_class: gatekept\ngit:\n  default_branch: main\ngatekeeping:\n  expose_external_remote: true\n""".lstrip(),
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                    "CODEXCTL_CONFIG_FILE": str(config_file),
                },
            ):
                cache_dir = state_dir / "cache" / f"{project_id}.git"
                cache_dir.mkdir(parents=True, exist_ok=True)

                env, volumes = _build_task_env_and_volumes(
                    project=load_project(project_id),
                    task_id="12",
                )

                # Verify EXTERNAL_REMOTE_URL is NOT set when upstream_url is missing
                self.assertNotIn("EXTERNAL_REMOTE_URL", env)
                # Verify gatekeeping mode settings are still correct
                self.assertEqual(env["CODE_REPO"], "file:///git-cache/cache.git")
                self.assertIn(f"{cache_dir}:/git-cache/cache.git:Z", volumes)
