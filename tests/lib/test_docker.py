import unittest
import unittest.mock

from luskctl.lib.containers.docker import build_images, generate_dockerfiles
from luskctl.lib.core.config import build_root
from test_utils import project_env


class DockerTests(unittest.TestCase):
    def test_generate_dockerfiles_outputs(self) -> None:
        project_id = "proj4"
        yaml = f"""\
project:
  id: {project_id}
git:
  upstream_url: https://example.com/repo.git
  default_branch: main
"""
        with project_env(yaml, project_id=project_id):
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

            l0_content = l0.read_text(encoding="utf-8")
            self.assertIn('LANG="en_US.UTF-8"', l0_content)
            self.assertIn('LC_ALL="en_US.UTF-8"', l0_content)
            self.assertIn('LANGUAGE="en_US:en"', l0_content)
            self.assertIn("locales", l0_content)
            self.assertIn("locale-gen en_US.UTF-8", l0_content)

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
        project_id = "proj_gated"
        yaml = f"""\
project:
  id: {project_id}
  security_class: gatekeeping
git:
  upstream_url: https://example.com/repo.git
  default_branch: main
"""
        with project_env(yaml, project_id=project_id):
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
        project_id = "proj_pipx_test"
        yaml = f"""\
project:
  id: {project_id}
git:
  upstream_url: https://example.com/repo.git
  default_branch: main
"""
        with project_env(yaml, project_id=project_id):
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

    def test_build_images_rebuild_agents_parameter(self) -> None:
        """Test that build_images respects the rebuild_agents parameter."""
        project_id = "proj_build_test"
        yaml = f"""\
project:
  id: {project_id}
git:
  upstream_url: https://example.com/repo.git
  default_branch: main
"""
        with project_env(yaml, project_id=project_id):
            generate_dockerfiles(project_id)

            # Mock subprocess.run to capture build commands
            build_commands = []

            def mock_run(cmd: list[str], **kwargs: object) -> unittest.mock.Mock:
                if isinstance(cmd, list) and "podman" in cmd and "build" in cmd:
                    build_commands.append(cmd)
                result = unittest.mock.Mock()
                result.returncode = 0
                return result

            with (
                unittest.mock.patch("subprocess.run", side_effect=mock_run),
                unittest.mock.patch("luskctl.lib.containers.docker._check_podman_available"),
            ):
                # Test default (L2 only)
                build_commands.clear()
                build_images(project_id)

                # Should only build L2 images (2 commands: l2-cli and l2-ui)
                self.assertEqual(len(build_commands), 2)
                for cmd in build_commands:
                    self.assertIn("L2.Dockerfile", " ".join(cmd))

                # Test rebuild_agents=True
                build_commands.clear()
                build_images(project_id, rebuild_agents=True)

                # Should build all images (5 commands: L0, L1-cli, L1-ui, L2-cli, L2-ui)
                self.assertEqual(len(build_commands), 5)
                # First command should be L0
                self.assertIn("L0.Dockerfile", " ".join(build_commands[0]))
                # Second should be L1-cli with AGENT_CACHE_BUST
                self.assertIn("L1.cli.Dockerfile", " ".join(build_commands[1]))
                self.assertIn("AGENT_CACHE_BUST", " ".join(build_commands[1]))
                # Third should be L1-ui
                self.assertIn("L1.ui.Dockerfile", " ".join(build_commands[2]))
                # Fourth and fifth should be L2
                self.assertIn("L2.Dockerfile", " ".join(build_commands[3]))
                self.assertIn("L2.Dockerfile", " ".join(build_commands[4]))

                # Test full_rebuild=True
                build_commands.clear()
                build_images(project_id, full_rebuild=True)

                # Should build all images with --no-cache
                self.assertEqual(len(build_commands), 5)
                # L0 should have --no-cache and --pull=always
                l0_cmd = " ".join(build_commands[0])
                self.assertIn("--no-cache", l0_cmd)
                self.assertIn("--pull=always", l0_cmd)
                # All other commands should have --no-cache
                for cmd in build_commands[1:]:
                    self.assertIn("--no-cache", " ".join(cmd))
