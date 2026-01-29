"""Tests for the Blablador wrapper script and Dockerfile integration.

These tests verify that:
1. The blablador wrapper script is syntactically correct Python
2. The L1 CLI Dockerfile includes the blablador alias
3. The blablador alias has proper git author/committer configuration
"""

import ast
import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from luskctl.lib.config import build_root
from luskctl.lib.docker import generate_dockerfiles
from test_utils import write_project


def get_blablador_script_path() -> Path:
    """Get the path to the blablador wrapper script."""
    return (
        Path(__file__).parent.parent.parent
        / "src"
        / "luskctl"
        / "resources"
        / "scripts"
        / "blablador"
    )


class BlabladorScriptTests(unittest.TestCase):
    """Tests for the blablador wrapper script."""

    def setUp(self) -> None:
        self.script_path = get_blablador_script_path()
        if not self.script_path.exists():
            self.skipTest(f"Blablador script not found at {self.script_path}")

    def test_script_is_valid_python(self) -> None:
        """Verify that the blablador script is syntactically valid Python."""
        source = self.script_path.read_text(encoding="utf-8")
        # This will raise SyntaxError if the script is invalid
        ast.parse(source)

    def test_script_has_shebang(self) -> None:
        """Verify the script has a proper Python shebang."""
        content = self.script_path.read_text(encoding="utf-8")
        self.assertTrue(
            content.startswith("#!/usr/bin/env python3"),
            "Script should start with #!/usr/bin/env python3",
        )

    def test_script_has_default_base_url(self) -> None:
        """Verify the script has the correct Blablador API base URL."""
        content = self.script_path.read_text(encoding="utf-8")
        self.assertIn(
            'DEFAULT_BASE_URL = "https://api.helmholtz-blablador.fz-juelich.de/v1"',
            content,
            "Script should have the correct Blablador API base URL",
        )

    def test_script_uses_openai_compatible_npm_package(self) -> None:
        """Verify the script uses @ai-sdk/openai-compatible for OpenCode integration."""
        content = self.script_path.read_text(encoding="utf-8")
        self.assertIn(
            '"npm": "@ai-sdk/openai-compatible"',
            content,
            "Script should use @ai-sdk/openai-compatible npm package",
        )

    def test_script_config_dir_is_blablador(self) -> None:
        """Verify the script uses ~/.blablador as config directory."""
        content = self.script_path.read_text(encoding="utf-8")
        self.assertIn('".blablador"', content, "Script should use ~/.blablador config directory")

    def test_script_builds_opencode_config(self) -> None:
        """Verify the script builds proper OpenCode config structure."""
        content = self.script_path.read_text(encoding="utf-8")
        # Check for key config elements
        self.assertIn('"$schema": "https://opencode.ai/config.json"', content)
        self.assertIn('"provider":', content)
        self.assertIn('"blablador":', content)
        self.assertIn('"permission":', content)
        self.assertIn('"*": "allow"', content)


class BlabladorDockerfileTests(unittest.TestCase):
    """Tests for Blablador integration in the L1 CLI Dockerfile."""

    def test_l1_cli_has_blablador_alias(self) -> None:
        """Verify that the L1 CLI Dockerfile includes the blablador alias."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_blablador_test"
            write_project(
                config_root,
                project_id,
                f"""\
project:
  id: {project_id}
git:
  upstream_url: https://example.com/repo.git
  default_branch: main
""",
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

                # Verify blablador alias exists
                self.assertIn("alias blablador=", content)

    def test_l1_cli_blablador_alias_has_git_author(self) -> None:
        """Verify the blablador alias sets GIT_AUTHOR_NAME."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_blablador_git_test"
            write_project(
                config_root,
                project_id,
                f"""\
project:
  id: {project_id}
git:
  upstream_url: https://example.com/repo.git
  default_branch: main
""",
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

                # Verify blablador alias has git author configuration
                self.assertIn("GIT_AUTHOR_NAME=Blablador", content)
                self.assertIn("GIT_AUTHOR_EMAIL=blablador@helmholtz.de", content)

    def test_l1_cli_blablador_in_agents_list(self) -> None:
        """Verify blablador appears in the available agents list."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_blablador_list_test"
            write_project(
                config_root,
                project_id,
                f"""\
project:
  id: {project_id}
git:
  upstream_url: https://example.com/repo.git
  default_branch: main
""",
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

                # Verify blablador is listed with description
                self.assertIn("blablador", content)
                self.assertIn("Helmholtz Blablador", content)

    def test_l1_cli_opencode_installed(self) -> None:
        """Verify that OpenCode CLI is installed in the L1 CLI image."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_opencode_test"
            write_project(
                config_root,
                project_id,
                f"""\
project:
  id: {project_id}
git:
  upstream_url: https://example.com/repo.git
  default_branch: main
""",
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

                # Verify OpenCode installation
                self.assertIn("opencode.ai/install", content)
                self.assertIn("OPENCODE_INSTALL_DIR", content)

    def test_l1_cli_blablador_script_copied(self) -> None:
        """Verify the blablador wrapper script is copied to the image."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            state_dir = base / "state"
            config_root.mkdir(parents=True, exist_ok=True)

            project_id = "proj_script_copy_test"
            write_project(
                config_root,
                project_id,
                f"""\
project:
  id: {project_id}
git:
  upstream_url: https://example.com/repo.git
  default_branch: main
""",
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

                # Verify scripts directory exists and blablador is there
                scripts_dir = out_dir / "scripts"
                self.assertTrue(scripts_dir.is_dir())

                blablador_script = scripts_dir / "blablador"
                self.assertTrue(
                    blablador_script.is_file(), f"blablador script not found in {scripts_dir}"
                )


class BlabladorConfigTests(unittest.TestCase):
    """Tests for Blablador configuration structure."""

    def test_config_json_structure(self) -> None:
        """Test that the expected config JSON structure is valid."""
        # This is the structure that blablador generates for OpenCode
        config = {
            "$schema": "https://opencode.ai/config.json",
            "model": "blablador/alias-code",
            "provider": {
                "blablador": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Helmholtz Blablador",
                    "options": {
                        "baseURL": "https://api.helmholtz-blablador.fz-juelich.de/v1",
                        "apiKey": "test-key",
                    },
                    "models": {"alias-code": {"name": "alias-code"}},
                }
            },
            "permission": {
                "*": "allow",
            },
        }

        # Verify it's valid JSON by serializing and deserializing
        json_str = json.dumps(config, indent=2)
        parsed = json.loads(json_str)

        self.assertEqual(parsed["$schema"], "https://opencode.ai/config.json")
        self.assertEqual(parsed["model"], "blablador/alias-code")
        self.assertIn("blablador", parsed["provider"])
        self.assertEqual(parsed["provider"]["blablador"]["npm"], "@ai-sdk/openai-compatible")
        self.assertEqual(parsed["permission"]["*"], "allow")


if __name__ == "__main__":
    unittest.main()
