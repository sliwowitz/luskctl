from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from codexctl.lib.projects import load_project
from codexctl.lib.tasks import _build_task_env_and_volumes, task_delete, task_new
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
