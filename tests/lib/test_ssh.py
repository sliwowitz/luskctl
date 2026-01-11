import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from luskctl.lib.ssh import init_project_ssh
from test_utils import mock_git_config, write_project


class SshTests(unittest.TestCase):
    def test_init_project_ssh_uses_existing_keys(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            ssh_dir = base / "ssh"
            config_root.mkdir(parents=True, exist_ok=True)
            ssh_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj5"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\nssh:\n  host_dir: {ssh_dir}\n""".lstrip(),
            )

            key_name = "id_test"
            (ssh_dir / key_name).write_text("dummy", encoding="utf-8")
            (ssh_dir / f"{key_name}.pub").write_text("dummy", encoding="utf-8")

            with (
                unittest.mock.patch.dict(os.environ, {"LUSKCTL_CONFIG_DIR": str(config_root)}),
                mock_git_config(),
                unittest.mock.patch("luskctl.lib.ssh.subprocess.run") as run_mock,
            ):
                result = init_project_ssh(project_id, key_name=key_name)

                run_mock.assert_not_called()
                cfg_path = Path(result["config_path"])
                self.assertTrue(cfg_path.is_file())
                cfg_text = cfg_path.read_text(encoding="utf-8")
                self.assertIn(f"IdentityFile ~/.ssh/{key_name}", cfg_text)
