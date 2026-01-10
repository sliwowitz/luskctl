import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from codexctl.lib.config import build_root
from codexctl.lib.docker import generate_dockerfiles
from test_utils import write_project


class DockerTests(unittest.TestCase):
    def test_generate_dockerfiles_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj4"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\ngit:\n  upstream_url: https://example.com/repo.git\n  default_branch: main\n""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                generate_dockerfiles(project_id)
                out_dir = build_root() / project_id
                l0 = out_dir / "L0.Dockerfile"
                l1_cli = out_dir / "L1.cli.Dockerfile"
                l1_ui = out_dir / "L1.ui.Dockerfile"
                l2 = out_dir / "L2.Dockerfile"

                self.assertTrue(l0.is_file())
                self.assertTrue(l1_cli.is_file())
                self.assertTrue(l1_ui.is_file())
                self.assertTrue(l2.is_file())

                content = l2.read_text(encoding="utf-8")
                self.assertIn(f'SSH_KEY_NAME="id_ed25519_{project_id}"', content)
                self.assertNotIn("{{DEFAULT_BRANCH}}", content)

                scripts_dir = out_dir / "scripts"
                self.assertTrue(scripts_dir.is_dir())
                script_files = [p for p in scripts_dir.iterdir() if p.is_file()]
                self.assertTrue(script_files)

                # For online projects, CODE_REPO should default to upstream URL
                self.assertIn('CODE_REPO="https://example.com/repo.git"', content)

    def test_generate_dockerfiles_gatekeeping_code_repo(self) -> None:
        """For gatekeeping projects, CODE_REPO_DEFAULT should be the git-gate path."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_gated"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\n  security_class: gatekeeping\ngit:\n  upstream_url: https://example.com/repo.git\n  default_branch: main\n""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                generate_dockerfiles(project_id)
                out_dir = build_root() / project_id
                l2 = out_dir / "L2.Dockerfile"

                content = l2.read_text(encoding="utf-8")
                # For gatekeeping projects, CODE_REPO should default to git-gate
                self.assertIn('CODE_REPO="file:///git-gate/gate.git"', content)
                # Should NOT contain the real upstream URL as CODE_REPO
                self.assertNotIn('CODE_REPO="https://example.com/repo.git"', content)
