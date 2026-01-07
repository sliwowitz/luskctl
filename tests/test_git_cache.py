from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from codexctl.git_cache import init_project_cache
from test_utils import write_project


class GitCacheTests(unittest.TestCase):
    def test_init_project_cache_ssh_requires_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            envs_dir = base / "envs"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj6"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\ngit:\n  upstream_url: git@github.com:org/repo.git\n""".lstrip(),
            )

            config_file = base / "config.yml"
            config_file.write_text(f"envs:\n  base_dir: {envs_dir}\n", encoding="utf-8")

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_CONFIG_FILE": str(config_file),
                },
            ):
                with self.assertRaises(SystemExit):
                    init_project_cache(project_id)

    def test_init_project_cache_https_clone(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj7"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\ngit:\n  upstream_url: https://example.com/repo.git\n""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                with unittest.mock.patch("codexctl.git_cache.subprocess.run") as run_mock:
                    run_mock.return_value.returncode = 0
                    result = init_project_cache(project_id)

                self.assertTrue(result["created"])
                self.assertIn("path", result)
                self.assertEqual(result["upstream_url"], "https://example.com/repo.git")

                call = run_mock.call_args
                self.assertIsNotNone(call)
                args, kwargs = call
                self.assertEqual(args[0][:3], ["git", "clone", "--mirror"])
                self.assertIn("env", kwargs)
