# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Tests for layered agent config resolution and presets."""

import json
import os
import tempfile
import unittest.mock
from pathlib import Path

import pytest

from terok.lib.containers.agent_config import build_agent_config_stack, resolve_agent_config
from terok.lib.core.projects import list_presets, load_preset, load_project
from test_utils import mock_git_config, write_project


def _env(
    config_root: Path,
    state_root: Path,
    global_config: Path | None = None,
    xdg_config_home: Path | None = None,
) -> dict[str, str]:
    """Build env dict for test isolation.

    Always sets XDG_CONFIG_HOME to prevent leaking the host value
    (which would let real user presets pollute test results).
    """
    env: dict[str, str] = {
        "TEROK_CONFIG_DIR": str(config_root),
        "TEROK_STATE_DIR": str(state_root),
        "XDG_CONFIG_HOME": str(xdg_config_home or config_root.parent / "xdg"),
    }
    if global_config:
        env["TEROK_CONFIG_FILE"] = str(global_config)
    return env


class TestResolveAgentConfig:
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
            assert result == {}

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
            assert result["model"] == "sonnet"
            assert len(result["subagents"]) == 1
            assert result["subagents"][0]["name"] == "a1"

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
            assert result["model"] == "haiku"
            assert result["max_turns"] == 5

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
            assert result["model"] == "opus"
            # max_turns inherited from global
            assert result["max_turns"] == 5

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
            assert result["model"] == "haiku"
            assert result["max_turns"] == 3

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
            assert result["model"] == "opus"
            assert result["max_turns"] == 99

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
            assert names == ["base-agent", "extra-agent"]

    def test_project_config_without_preset(self) -> None:
        """Project agent config resolves correctly without a preset."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(
                config_root,
                "proj2",
                "project:\n  id: proj2\nagent:\n  model: sonnet\n"
                "  subagents:\n    - name: sa1\n      default: true\n",
            )

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    result = resolve_agent_config("proj2")
            assert result["model"] == "sonnet"
            assert result["subagents"][0]["name"] == "sa1"


class TestPreset:
    """Tests for list_presets() and load_preset()."""

    def test_list_presets_no_project_or_global(self) -> None:
        """No project/global presets — only bundled presets are returned."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    result = list_presets("proj")
            non_bundled = [info for info in result if info.source != "bundled"]
            assert non_bundled == []
            # Bundled presets are always present
            bundled = [info for info in result if info.source == "bundled"]
            assert len(bundled) > 0

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
            project_presets = [info for info in result if info.source == "project"]
            assert [info.name for info in project_presets] == ["alpha", "beta"]

    def test_load_preset_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    with pytest.raises(SystemExit):
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
                    data, path = load_preset("proj", "reviewer")
            assert data["model"] == "sonnet"
            assert data["max_turns"] == 10
            assert path == presets_dir / "reviewer.yml"

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
                    data, path = load_preset("proj", "alt")
            assert data["model"] == "opus"
            assert path == presets_dir / "alt.yaml"

    def test_presets_dir_property(self) -> None:
        """Project.presets_dir points to presets/ under project root."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    p = load_project("proj")
            assert p.presets_dir == p.root / "presets"


class TestPresetFileRef:
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
                    data, _path = load_preset("proj", "custom")
            # File path should be resolved to absolute
            resolved = data["subagents"][0]["file"]
            expected = str((presets_dir / "agents" / "reviewer.md").resolve())
            assert resolved == expected

    def test_global_preset_fallback(self) -> None:
        """load_preset finds a preset in the global presets dir when not in project."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            # Create global preset via XDG_CONFIG_HOME
            xdg = base / "xdg"
            global_presets = xdg / "terok" / "presets"
            global_presets.mkdir(parents=True, exist_ok=True)
            (global_presets / "shared.yml").write_text(
                "model: haiku\nmax_turns: 2\n", encoding="utf-8"
            )

            env = _env(config_root, base / "s", xdg_config_home=xdg)
            with unittest.mock.patch.dict(os.environ, env):
                with mock_git_config():
                    data, path = load_preset("proj", "shared")
            assert data["model"] == "haiku"
            assert path == global_presets / "shared.yml"

    def test_project_preset_shadows_global(self) -> None:
        """Project preset shadows a global preset with the same name."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            # Create global preset
            xdg = base / "xdg"
            global_presets = xdg / "terok" / "presets"
            global_presets.mkdir(parents=True, exist_ok=True)
            (global_presets / "fast.yml").write_text("model: haiku\n", encoding="utf-8")

            # Create project preset with same name
            proj_presets = config_root / "proj" / "presets"
            proj_presets.mkdir(parents=True, exist_ok=True)
            (proj_presets / "fast.yml").write_text("model: opus\n", encoding="utf-8")

            env = _env(config_root, base / "s", xdg_config_home=xdg)
            with unittest.mock.patch.dict(os.environ, env):
                with mock_git_config():
                    data, path = load_preset("proj", "fast")
            assert data["model"] == "opus"
            assert path == proj_presets / "fast.yml"

    def test_global_preset_file_resolution(self) -> None:
        """Subagent file: paths in global presets resolve relative to global presets dir."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            xdg = base / "xdg"
            global_presets = xdg / "terok" / "presets"
            global_presets.mkdir(parents=True, exist_ok=True)
            (global_presets / "with-file.yml").write_text(
                "subagents:\n  - name: sa\n    file: ./agents/custom.md\n",
                encoding="utf-8",
            )

            env = _env(config_root, base / "s", xdg_config_home=xdg)
            with unittest.mock.patch.dict(os.environ, env):
                with mock_git_config():
                    data, _path = load_preset("proj", "with-file")
            resolved = data["subagents"][0]["file"]
            expected = str((global_presets / "agents" / "custom.md").resolve())
            assert resolved == expected


class TestGlobalPresetList:
    """Tests for list_presets() with global presets."""

    def test_list_presets_includes_global(self) -> None:
        """list_presets returns global and project presets with source labels."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            # Global preset
            xdg = base / "xdg"
            global_presets = xdg / "terok" / "presets"
            global_presets.mkdir(parents=True, exist_ok=True)
            (global_presets / "shared.yml").write_text("model: haiku\n", encoding="utf-8")

            # Project preset
            proj_presets = config_root / "proj" / "presets"
            proj_presets.mkdir(parents=True, exist_ok=True)
            (proj_presets / "local.yml").write_text("model: opus\n", encoding="utf-8")

            env = _env(config_root, base / "s", xdg_config_home=xdg)
            with unittest.mock.patch.dict(os.environ, env):
                with mock_git_config():
                    result = list_presets("proj")
            non_bundled = {info.name: info.source for info in result if info.source != "bundled"}
            assert non_bundled == {"local": "project", "shared": "global"}

    def test_list_presets_project_shadows_global(self) -> None:
        """Project preset with same name replaces global in listing."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            xdg = base / "xdg"
            global_presets = xdg / "terok" / "presets"
            global_presets.mkdir(parents=True, exist_ok=True)
            (global_presets / "fast.yml").write_text("model: haiku\n", encoding="utf-8")

            proj_presets = config_root / "proj" / "presets"
            proj_presets.mkdir(parents=True, exist_ok=True)
            (proj_presets / "fast.yml").write_text("model: opus\n", encoding="utf-8")

            env = _env(config_root, base / "s", xdg_config_home=xdg)
            with unittest.mock.patch.dict(os.environ, env):
                with mock_git_config():
                    result = list_presets("proj")
            non_bundled = [info for info in result if info.source != "bundled"]
            assert len(non_bundled) == 1
            assert non_bundled[0].name == "fast"
            assert non_bundled[0].source == "project"


class TestGlobalPresetProvenance:
    """Tests for global preset provenance in config stack."""

    def test_global_preset_scope_label(self) -> None:
        """Config stack labels global presets as 'preset (global)'."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            xdg = base / "xdg"
            global_presets = xdg / "terok" / "presets"
            global_presets.mkdir(parents=True, exist_ok=True)
            (global_presets / "shared.yml").write_text("model: haiku\n", encoding="utf-8")

            env = _env(config_root, base / "s", xdg_config_home=xdg)
            with unittest.mock.patch.dict(os.environ, env):
                with mock_git_config():
                    stack = build_agent_config_stack("proj", preset="shared")
            levels = [s.level for s in stack.scopes]
            assert "preset (global)" in levels

    def test_project_preset_scope_label(self) -> None:
        """Config stack labels project presets as 'preset (project)'."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            proj_presets = config_root / "proj" / "presets"
            proj_presets.mkdir(parents=True, exist_ok=True)
            (proj_presets / "fast.yml").write_text("model: haiku\n", encoding="utf-8")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    stack = build_agent_config_stack("proj", preset="fast")
            levels = [s.level for s in stack.scopes]
            assert "preset (project)" in levels


def _any_bundled_name() -> str:
    """Return the name of any bundled preset (for tests that need a concrete name)."""
    from terok.lib.core.config import bundled_presets_dir

    bdir = bundled_presets_dir()
    for p in bdir.iterdir():
        if p.is_file() and p.suffix in (".yml", ".yaml"):
            return p.stem
    raise RuntimeError("No bundled presets found — cannot run bundled preset tests")


class TestBundledPreset:
    """Tests for bundled (shipped) presets.

    These tests are name-agnostic: they discover whatever presets happen to
    be shipped in ``resources/presets/`` rather than hardcoding specific names.
    Swap the bundled YAML files freely — only the infrastructure is tested here.
    """

    def test_bundled_presets_discoverable(self) -> None:
        """At least one bundled preset appears in list_presets."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    result = list_presets("proj")
            bundled = [info for info in result if info.source == "bundled"]
            assert len(bundled) > 0, "Expected at least one bundled preset"

    def test_bundled_preset_loadable(self) -> None:
        """Any bundled preset can be loaded via load_preset."""
        name = _any_bundled_name()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    data, path = load_preset("proj", name)
            assert isinstance(data, dict)
            assert path.is_file()

    def test_global_shadows_bundled(self) -> None:
        """A global preset with the same name as a bundled preset wins."""
        name = _any_bundled_name()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            xdg = base / "xdg"
            global_presets = xdg / "terok" / "presets"
            global_presets.mkdir(parents=True, exist_ok=True)
            (global_presets / f"{name}.yml").write_text(
                "model: opus\nmax_turns: 99\n", encoding="utf-8"
            )

            env = _env(config_root, base / "s", xdg_config_home=xdg)
            with unittest.mock.patch.dict(os.environ, env):
                with mock_git_config():
                    data, path = load_preset("proj", name)
            # Global version wins
            assert data["model"] == "opus"
            assert data["max_turns"] == 99
            assert path == global_presets / f"{name}.yml"

    def test_project_shadows_bundled(self) -> None:
        """A project preset with the same name as a bundled preset wins."""
        name = _any_bundled_name()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            proj_presets = config_root / "proj" / "presets"
            proj_presets.mkdir(parents=True, exist_ok=True)
            (proj_presets / f"{name}.yml").write_text("model: haiku\n", encoding="utf-8")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    data, path = load_preset("proj", name)
            assert data["model"] == "haiku"
            assert path == proj_presets / f"{name}.yml"

    def test_bundled_preset_scope_label(self) -> None:
        """Config stack labels bundled presets as 'preset (bundled)'."""
        name = _any_bundled_name()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            with unittest.mock.patch.dict(os.environ, _env(config_root, base / "s")):
                with mock_git_config():
                    stack = build_agent_config_stack("proj", preset=name)
            levels = [s.level for s in stack.scopes]
            assert "preset (bundled)" in levels

    def test_shadowed_bundled_gets_correct_source(self) -> None:
        """Shadowing one bundled preset changes its source; others stay bundled."""
        name = _any_bundled_name()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            config_root = base / "config"
            write_project(config_root, "proj", "project:\n  id: proj\n")

            xdg = base / "xdg"
            global_presets = xdg / "terok" / "presets"
            global_presets.mkdir(parents=True, exist_ok=True)
            (global_presets / f"{name}.yml").write_text("model: opus\n", encoding="utf-8")

            env = _env(config_root, base / "s", xdg_config_home=xdg)
            with unittest.mock.patch.dict(os.environ, env):
                with mock_git_config():
                    result = list_presets("proj")
            by_name = {info.name: info.source for info in result}
            assert by_name[name] == "global"
            # At least one other bundled preset should remain bundled
            remaining_bundled = [n for n, s in by_name.items() if s == "bundled"]
            assert len(remaining_bundled) > 0


class TestInjectOpencodeInstructions:
    """Tests for _inject_opencode_instructions()."""

    def test_creates_file_if_missing(self) -> None:
        """Creates opencode.json with instructions entry and $schema if file does not exist."""
        from terok.lib.containers.agents import _inject_opencode_instructions

        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "opencode.json"
            _inject_opencode_instructions(config_path)

            assert config_path.is_file()
            data = json.loads(config_path.read_text(encoding="utf-8"))
            assert data["instructions"] == ["/home/dev/.terok/instructions.md"]
            assert data["$schema"] == "https://opencode.ai/config.json"

    def test_idempotent_when_already_present(self) -> None:
        """Does not duplicate the instructions entry on repeated calls."""
        from terok.lib.containers.agents import _inject_opencode_instructions

        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "opencode.json"
            _inject_opencode_instructions(config_path)
            _inject_opencode_instructions(config_path)

            data = json.loads(config_path.read_text(encoding="utf-8"))
            assert data["instructions"] == ["/home/dev/.terok/instructions.md"]

    def test_preserves_existing_instructions(self) -> None:
        """Appends to existing instructions list without removing entries."""
        from terok.lib.containers.agents import _inject_opencode_instructions

        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "opencode.json"
            config_path.write_text(
                json.dumps({"instructions": ["/some/other/file.md"]}), encoding="utf-8"
            )
            _inject_opencode_instructions(config_path)

            data = json.loads(config_path.read_text(encoding="utf-8"))
            assert data["instructions"] == [
                "/some/other/file.md",
                "/home/dev/.terok/instructions.md",
            ]

    def test_preserves_existing_config_keys(self) -> None:
        """Preserves other keys in the opencode.json file."""
        from terok.lib.containers.agents import _inject_opencode_instructions

        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "opencode.json"
            config_path.write_text(
                json.dumps({"model": "test/model", "provider": {"test": {}}}),
                encoding="utf-8",
            )
            _inject_opencode_instructions(config_path)

            data = json.loads(config_path.read_text(encoding="utf-8"))
            assert data["model"] == "test/model"
            assert data["provider"] == {"test": {}}
            assert data["instructions"] == ["/home/dev/.terok/instructions.md"]

    def test_creates_parent_directories(self) -> None:
        """Creates parent directories if they do not exist."""
        from terok.lib.containers.agents import _inject_opencode_instructions

        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "nested" / "dir" / "opencode.json"
            _inject_opencode_instructions(config_path)

            assert config_path.is_file()
            data = json.loads(config_path.read_text(encoding="utf-8"))
            assert data["instructions"] == ["/home/dev/.terok/instructions.md"]
            assert data["$schema"] == "https://opencode.ai/config.json"

    def test_handles_invalid_json(self) -> None:
        """Overwrites file with valid config if existing JSON is invalid."""
        from terok.lib.containers.agents import _inject_opencode_instructions

        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "opencode.json"
            config_path.write_text("not valid json", encoding="utf-8")
            _inject_opencode_instructions(config_path)

            data = json.loads(config_path.read_text(encoding="utf-8"))
            assert data["instructions"] == ["/home/dev/.terok/instructions.md"]
            assert data["$schema"] == "https://opencode.ai/config.json"

    def test_preserves_existing_schema(self) -> None:
        """Does not overwrite $schema if already present in existing config."""
        from terok.lib.containers.agents import _inject_opencode_instructions

        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "opencode.json"
            config_path.write_text(
                json.dumps({"$schema": "https://opencode.ai/config.json", "model": "x/y"}),
                encoding="utf-8",
            )
            _inject_opencode_instructions(config_path)

            data = json.loads(config_path.read_text(encoding="utf-8"))
            assert data["$schema"] == "https://opencode.ai/config.json"
            assert data["model"] == "x/y"


class TestValidateProjectId:
    """Tests for validate_project_id error messages."""

    def test_error_message_mentions_first_char(self) -> None:
        """Error message describes the first-character requirement."""
        from terok.lib.core.project_model import validate_project_id

        with pytest.raises(SystemExit) as ctx:
            validate_project_id("-bad")
        msg = str(ctx.value)
        assert "must start with a lowercase letter or digit" in msg

    def test_uppercase_rejected(self) -> None:
        """Uppercase letters in project ID are rejected."""
        from terok.lib.core.project_model import validate_project_id

        with pytest.raises(SystemExit) as ctx:
            validate_project_id("MyProject")
        assert "Invalid project ID" in str(ctx.value)
