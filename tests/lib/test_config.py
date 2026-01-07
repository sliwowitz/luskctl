from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from codexctl.lib import config as cfg


class ConfigTests(unittest.TestCase):
    def test_global_config_search_paths_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            with unittest.mock.patch.dict(os.environ, {"CODEXCTL_CONFIG_FILE": str(cfg_path)}):
                paths = cfg.global_config_search_paths()
                self.assertEqual(paths, [cfg_path.expanduser().resolve()])

    def test_global_config_path_prefers_xdg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            xdg = Path(td)
            config_file = xdg / "codexctl" / "config.yml"
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config_file.write_text("ui:\n  base_port: 7000\n", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg)}, clear=False):
                path = cfg.global_config_path()
                self.assertEqual(path, config_file.resolve())

    def test_state_root_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with unittest.mock.patch.dict(os.environ, {"CODEXCTL_STATE_DIR": td}):
                self.assertEqual(cfg.state_root(), Path(td).resolve())

    def test_state_root_config_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            state_dir = Path(td) / "state"
            cfg_path.write_text(f"paths:\n  state_root: {state_dir}\n", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"CODEXCTL_CONFIG_FILE": str(cfg_path)}):
                self.assertEqual(cfg.state_root(), state_dir.resolve())

    def test_user_projects_root_config_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            projects_dir = Path(td) / "projects"
            cfg_path.write_text(f"paths:\n  user_projects_root: {projects_dir}\n", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"CODEXCTL_CONFIG_FILE": str(cfg_path)}):
                self.assertEqual(cfg.user_projects_root(), projects_dir.resolve())

    def test_ui_and_envs_values_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            envs_dir = Path(td) / "envs"
            cfg_path.write_text(
                "ui:\n"
                "  base_port: 8123\n"
                "envs:\n"
                f"  base_dir: {envs_dir}\n",
                encoding="utf-8",
            )
            with unittest.mock.patch.dict(os.environ, {"CODEXCTL_CONFIG_FILE": str(cfg_path)}):
                self.assertEqual(cfg.get_ui_base_port(), 8123)
                self.assertEqual(cfg.get_envs_base_dir(), envs_dir.resolve())
