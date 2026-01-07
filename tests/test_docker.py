from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from codexctl.config import build_root
from codexctl.docker import generate_dockerfiles
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
                l1 = out_dir / "L1.Dockerfile"
                l2 = out_dir / "L2.Dockerfile"
                l3 = out_dir / "L3.Dockerfile"

                self.assertTrue(l1.is_file())
                self.assertTrue(l2.is_file())
                self.assertTrue(l3.is_file())

                content = l1.read_text(encoding="utf-8")
                self.assertIn(f"SSH_KEY_NAME=\"id_ed25519_{project_id}\"", content)
                self.assertNotIn("{{DEFAULT_BRANCH}}", content)

                scripts_dir = out_dir / "scripts"
                self.assertTrue(scripts_dir.is_dir())
                script_files = [p for p in scripts_dir.iterdir() if p.is_file()]
                self.assertTrue(script_files)
