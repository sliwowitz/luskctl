from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from codexctl.lib.git_gate import init_project_gate, get_gate_last_commit
from test_utils import write_project


class GitGateTests(unittest.TestCase):
    def test_init_project_gate_ssh_requires_config(self) -> None:
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
                    init_project_gate(project_id)

    def test_init_project_gate_https_clone(self) -> None:
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
                with unittest.mock.patch("codexctl.lib.git_gate.subprocess.run") as run_mock:
                    run_mock.return_value.returncode = 0
                    result = init_project_gate(project_id)

                self.assertTrue(result["created"])
                self.assertIn("path", result)
                self.assertEqual(result["upstream_url"], "https://example.com/repo.git")

                call = run_mock.call_args
                self.assertIsNotNone(call)
                args, kwargs = call
                self.assertEqual(args[0][:3], ["git", "clone", "--mirror"])
                self.assertIn("env", kwargs)

    def test_get_gate_last_commit_no_gate(self) -> None:
        """Test get_gate_last_commit when gate doesn't exist."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj8"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                },
            ):
                result = get_gate_last_commit(project_id)
                self.assertIsNone(result)

    def test_get_gate_last_commit_with_gate(self) -> None:
        """Test get_gate_last_commit when gate exists."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)

            project_id = "proj9"
            write_project(
                config_root,
                project_id,
                f"""
project:
  id: {project_id}
git:
  upstream_url: https://example.com/repo.git
""".lstrip(),
            )

            # Create a fake gate directory
            gate_dir = state_dir / "gate" / f"{project_id}.git"
            gate_dir.mkdir(parents=True, exist_ok=True)

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "CODEXCTL_CONFIG_DIR": str(config_root),
                    "CODEXCTL_STATE_DIR": str(state_dir),
                },
            ):
                # Mock the git log command to return sample commit data
                mock_result = unittest.mock.Mock()
                mock_result.returncode = 0
                mock_result.stdout = "abc123def456|2023-01-01 12:00:00 +0000|Test commit message|John Doe\n"

                with unittest.mock.patch("codexctl.lib.git_gate.subprocess.run", return_value=mock_result):
                    result = get_gate_last_commit(project_id)

                self.assertIsNotNone(result)
                self.assertEqual(result["commit_hash"], "abc123def456")
                self.assertEqual(result["commit_date"], "2023-01-01 12:00:00 +0000")
                self.assertEqual(result["commit_message"], "Test commit message")
                self.assertEqual(result["commit_author"], "John Doe")
