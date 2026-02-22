"""Tests for layered agent config resolution and presets."""

import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from luskctl.lib.containers.agent_config import resolve_agent_config
from luskctl.lib.core.projects import list_presets, load_preset, load_project
from test_utils import mock_git_config, write_project


def _env(config_root: Path, state_root: Path, global_config: Path | None = None) -> dict:
    """Build env dict for test isolation."""
    env = {
        "LUSKCTL_CONFIG_DIR": str(config_root),
        "LUSKCTL_STATE_DIR": str(state_root),
    }
    if global_config:
        env["LUSKCTL_CONFIG_FILE"] = str(global_config)
    return env


class ResolveAgentConfigTests(unittest.TestCase):
    """Tests for resolve_agent_config()."""

    def test_empty_config_all_levels(self) -> None:
        """Returns {} when no agent config at any level."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "empty", "project:\n  id: empty\n")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    result = resolve_agent_config("empty")
            self.assertEqual(result, {})

    def test_project_only(self) -> None:
        """Project-level agent config is returned when no other levels."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(
                config_root,
                "proj",
                "project:\n  id: proj\nagent:\n  model: sonnet\n  subagents:\n"
                "    - name: a1\n      default: true\n",
            )

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    result = resolve_agent_config("proj")
            self.assertEqual(result["model"], "sonnet")
            self.assertEqual(len(result["subagents"]), 1)
            self.assertEqual(result["subagents"][0]["name"], "a1")

    def test_global_provides_defaults(self) -> None:
        """Global agent config provides defaults when project has none."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            global_cfg = base / "global.yml"
            global_cfg.write_text("agent:\n  model: haiku\n  max_turns: 5\n", encoding="utf-8")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s", global_cfg)):
                with mock_git_config():
                    result = resolve_agent_config("proj")
            self.assertEqual(result["model"], "haiku")
            self.assertEqual(result["max_turns"], 5)

    def test_project_overrides_global(self) -> None:
        """Project-level config overrides global defaults."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(
                config_root,
                "proj",
                "project:\n  id: proj\nagent:\n  model: opus\n",
            )

            global_cfg = base / "global.yml"
            global_cfg.write_text("agent:\n  model: haiku\n  max_turns: 5\n", encoding="utf-8")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s", global_cfg)):
                with mock_git_config():
                    result = resolve_agent_config("proj")
            self.assertEqual(result["model"], "opus")
            # max_turns inherited from global
            self.assertEqual(result["max_turns"], 5)

    def test_preset_override(self) -> None:
        """Preset overrides project config."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(
                config_root,
                "proj",
                "project:\n  id: proj\nagent:\n  model: sonnet\n",
            )

            # Create preset
            presets_dir = config_root / "proj" / "presets"
            presets_dir.mkdir(parents=True, exist_ok=True)
            (presets_dir / "fast.yml").write_text("model: haiku\nmax_turns: 3\n", encoding="utf-8")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    result = resolve_agent_config("proj", preset="fast")
            self.assertEqual(result["model"], "haiku")
            self.assertEqual(result["max_turns"], 3)

    def test_cli_overrides_all(self) -> None:
        """CLI overrides take highest priority."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(
                config_root,
                "proj",
                "project:\n  id: proj\nagent:\n  model: sonnet\n",
            )

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    result = resolve_agent_config(
                        "proj", cli_overrides={"model": "opus", "max_turns": 99}
                    )
            self.assertEqual(result["model"], "opus")
            self.assertEqual(result["max_turns"], 99)

    def test_inherit_extends_subagents(self) -> None:
        """Preset with _inherit extends project subagents list."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(
                config_root,
                "proj",
                "project:\n  id: proj\nagent:\n  subagents:\n"
                "    - name: base-agent\n      default: true\n",
            )

            presets_dir = config_root / "proj" / "presets"
            presets_dir.mkdir(parents=True, exist_ok=True)
            (presets_dir / "extend.yml").write_text(
                "subagents:\n  - _inherit\n  - name: extra-agent\n    default: true\n",
                encoding="utf-8",
            )

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    result = resolve_agent_config("proj", preset="extend")
            names = [s["name"] for s in result["subagents"] if isinstance(s, dict)]
            self.assertEqual(names, ["base-agent", "extra-agent"])

    def test_legacy_compat_no_preset(self) -> None:
        """Existing project.yml works unchanged without preset."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(
                config_root,
                "legacy",
                "project:\n  id: legacy\nagent:\n  model: sonnet\n"
                "  subagents:\n    - name: sa1\n      default: true\n",
            )

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    result = resolve_agent_config("legacy")
            self.assertEqual(result["model"], "sonnet")
            self.assertEqual(result["subagents"][0]["name"], "sa1")


class PresetTests(unittest.TestCase):
    """Tests for list_presets() and load_preset()."""

    def test_list_presets_empty(self) -> None:
        """No presets dir returns empty list."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    result = list_presets("proj")
            self.assertEqual(result, [])

    def test_list_presets_found(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            presets_dir = config_root / "proj" / "presets"
            presets_dir.mkdir(parents=True, exist_ok=True)
            (presets_dir / "alpha.yml").write_text("model: haiku\n", encoding="utf-8")
            (presets_dir / "beta.yaml").write_text("model: sonnet\n", encoding="utf-8")
            (presets_dir / "ignore.txt").write_text("not a preset\n", encoding="utf-8")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    result = list_presets("proj")
            self.assertEqual(result, ["alpha", "beta"])

    def test_load_preset_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    with self.assertRaises(SystemExit):
                        load_preset("proj", "nonexistent")

    def test_load_preset_found(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            presets_dir = config_root / "proj" / "presets"
            presets_dir.mkdir(parents=True, exist_ok=True)
            (presets_dir / "reviewer.yml").write_text(
                "model: sonnet\nmax_turns: 10\n", encoding="utf-8"
            )

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    data = load_preset("proj", "reviewer")
            self.assertEqual(data["model"], "sonnet")
            self.assertEqual(data["max_turns"], 10)

    def test_load_preset_yaml_extension(self) -> None:
        """Preset with .yaml extension is also found."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            presets_dir = config_root / "proj" / "presets"
            presets_dir.mkdir(parents=True, exist_ok=True)
            (presets_dir / "alt.yaml").write_text("model: opus\n", encoding="utf-8")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    data = load_preset("proj", "alt")
            self.assertEqual(data["model"], "opus")

    def test_presets_dir_property(self) -> None:
        """Project.presets_dir points to presets/ under project root."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    p = load_project("proj")
            self.assertEqual(p.presets_dir, p.root / "presets")


class PresetFileRefTests(unittest.TestCase):
    """Tests for file references within presets."""

    def test_preset_resolves_relative_subagent_file(self) -> None:
        """Subagent file: paths in presets are resolved relative to presets dir."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            presets_dir = config_root / "proj" / "presets"
            presets_dir.mkdir(parents=True, exist_ok=True)
            (presets_dir / "custom.yml").write_text(
                "subagents:\n  - name: from-file\n    file: ./agents/reviewer.md\n",
                encoding="utf-8",
            )

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    data = load_preset("proj", "custom")
            # File path should be resolved to absolute
            resolved = data["subagents"][0]["file"]
            expected = str((presets_dir / "agents" / "reviewer.md").resolve())
            self.assertEqual(resolved, expected)
