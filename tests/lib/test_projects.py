import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from luskctl.lib.config import build_root, state_root
from luskctl.lib.projects import get_project_state, list_projects, load_project
from test_utils import write_project


class ProjectTests(unittest.TestCase):
    def test_load_project_gatekeeping_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj1"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\n  security_class: gatekeeping\ngit:\n  upstream_url: https://example.com/repo.git\n""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                },
            ):
                proj = load_project(project_id)
                self.assertEqual(proj.id, project_id)
                self.assertEqual(proj.security_class, "gatekeeping")
                self.assertEqual(proj.tasks_root, (state_root() / "tasks" / project_id).resolve())
                self.assertEqual(
                    proj.gate_path, (state_root() / "gate" / f"{project_id}.git").resolve()
                )
                self.assertEqual(proj.staging_root, (build_root() / project_id).resolve())

    def test_list_projects_prefers_user(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            system_root = base / "system"
            user_root = base / "user"
            system_root.mkdir(parents=True, exist_ok=True)
            user_projects = user_root / "luskctl" / "projects"

            project_id = "proj2"
            write_project(
                system_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\ngit:\n  upstream_url: https://system.example/repo.git\n""".lstrip(),
            )
            write_project(
                user_projects,
                project_id,
                f"""\nproject:\n  id: {project_id}\ngit:\n  upstream_url: https://user.example/repo.git\n""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(system_root),
                    "XDG_CONFIG_HOME": str(user_root),
                },
            ):
                projects = list_projects()
                self.assertEqual(len(projects), 1)
                self.assertEqual(projects[0].upstream_url, "https://user.example/repo.git")
                self.assertEqual(projects[0].root, (user_projects / project_id).resolve())

    def test_get_project_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            envs_dir = base / "envs"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj3"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\ngit:\n  upstream_url: https://example.com/repo.git\n""".lstrip(),
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
                stage_dir = build_root() / project_id
                stage_dir.mkdir(parents=True, exist_ok=True)
                for name in (
                    "L0.Dockerfile",
                    "L1.cli.Dockerfile",
                    "L1.ui.Dockerfile",
                    "L2.Dockerfile",
                ):
                    (stage_dir / name).write_text("", encoding="utf-8")

                ssh_dir = envs_dir / f"_ssh-config-{project_id}"
                ssh_dir.mkdir(parents=True, exist_ok=True)
                (ssh_dir / "config").write_text("", encoding="utf-8")

                gate_dir = state_root() / "gate" / f"{project_id}.git"
                gate_dir.mkdir(parents=True, exist_ok=True)

                with unittest.mock.patch("luskctl.lib.projects.subprocess.run") as run_mock:
                    run_mock.return_value.returncode = 0
                    state = get_project_state(project_id)

                self.assertEqual(
                    state,
                    {
                        "dockerfiles": True,
                        "dockerfiles_old": True,
                        "images": True,
                        "images_old": True,
                        "ssh": True,
                        "gate": True,
                        "gate_last_commit": None,
                    },
                )
