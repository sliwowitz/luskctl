import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from luskctl.lib.config import build_root
from luskctl.lib.docker import generate_dockerfiles
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
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
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
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
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

    def test_l1_cli_pipx_inject_has_env_vars(self) -> None:
        """Verify that PIPX environment variables are set globally and pipx commands use them."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_pipx_test"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\ngit:\n  upstream_url: https://example.com/repo.git\n  default_branch: main\n""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                },
            ):
                generate_dockerfiles(project_id)
                out_dir = build_root() / project_id
                l1_cli = out_dir / "L1.cli.Dockerfile"

                content = l1_cli.read_text(encoding="utf-8")
                # Verify that PIPX_HOME and PIPX_BIN_DIR are set as ENV variables
                self.assertIn("PIPX_HOME=/opt/pipx", content)
                self.assertIn("PIPX_BIN_DIR=/usr/local/bin", content)
                # Verify that pipx commands use these environment variables (no inline vars)
                self.assertIn("pipx install mistral-vibe", content)
                self.assertIn("pipx inject mistral-vibe mistralai", content)

    def test_build_images_build_all_parameter(self) -> None:
        """Test that build_images respects the build_all parameter."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_build_test"
            write_project(
                config_root,
                project_id,
                f"""\nproject:\n  id: {project_id}\ngit:\n  upstream_url: https://example.com/repo.git\n  default_branch: main\n""".lstrip(),
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "LUSKCTL_CONFIG_DIR": str(config_root),
                    "LUSKCTL_STATE_DIR": str(state_dir),
                },
            ):
                from luskctl.lib.docker import build_images

                generate_dockerfiles(project_id)

                # Mock subprocess.run to capture build commands
                build_commands = []

                def mock_run(cmd, **kwargs):
                    if isinstance(cmd, list) and "podman" in cmd and "build" in cmd:
                        build_commands.append(cmd)
                    # Create a mock result
                    result = unittest.mock.Mock()
                    result.returncode = 0
                    return result

                with unittest.mock.patch("subprocess.run", side_effect=mock_run):
                    # Test build_all=False (default)
                    build_commands.clear()
                    try:
                        build_images(project_id, build_all=False)
                    except Exception:
                        pass  # We're mocking, so it might fail

                    # Should only build L2 images (2 commands: l2-cli and l2-ui)
                    self.assertEqual(len(build_commands), 2)
                    for cmd in build_commands:
                        self.assertIn("L2.Dockerfile", " ".join(cmd))

                    # Test build_all=True
                    build_commands.clear()
                    try:
                        build_images(project_id, build_all=True)
                    except Exception:
                        pass  # We're mocking, so it might fail

                    # Should build all images (5 commands: L0, L1-cli, L1-ui, L2-cli, L2-ui)
                    self.assertEqual(len(build_commands), 5)
                    # First command should be L0
                    self.assertIn("L0.Dockerfile", " ".join(build_commands[0]))
                    # Second and third should be L1
                    self.assertIn("L1.cli.Dockerfile", " ".join(build_commands[1]))
                    self.assertIn("L1.ui.Dockerfile", " ".join(build_commands[2]))
                    # Fourth and fifth should be L2
                    self.assertIn("L2.Dockerfile", " ".join(build_commands[3]))
                    self.assertIn("L2.Dockerfile", " ".join(build_commands[4]))
