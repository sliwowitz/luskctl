from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codexctl.ssh import init_project_ssh


def _write_project(root: Path, project_id: str, yaml_text: str) -> Path:
    proj_dir = root / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "project.yml").write_text(yaml_text, encoding="utf-8")
    return proj_dir


class SshTests(unittest.TestCase):
    def test_init_project_ssh_uses_existing_keys(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            ssh_dir = base / "ssh"
            config_root.mkdir(parents=True, exist_ok=True)
            ssh_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj5"
            _write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\nssh:\n  host_dir: {ssh_dir}\n""".lstrip(),
            )

            key_name = "id_test"
            (ssh_dir / key_name).write_text("dummy", encoding="utf-8")
            (ssh_dir / f"{key_name}.pub").write_text("dummy", encoding="utf-8")

            with mock.patch.dict(os.environ, {"CODEXCTL_CONFIG_DIR": str(config_root)}):
                with mock.patch("codexctl.ssh.subprocess.run") as run_mock:
                    result = init_project_ssh(project_id, key_name=key_name)

                run_mock.assert_not_called()
                cfg_path = Path(result["config_path"])
                self.assertTrue(cfg_path.is_file())
                cfg_text = cfg_path.read_text(encoding="utf-8")
                self.assertIn(f"IdentityFile ~/.ssh/{key_name}", cfg_text)
