# SPDX-FileCopyrightText: 2025 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from terok.lib.core import config as cfg


class ConfigTests(unittest.TestCase):
    def test_global_config_search_paths_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            with unittest.mock.patch.dict(os.environ, {"TEROK_CONFIG_FILE": str(cfg_path)}):
                paths = cfg.global_config_search_paths()
                self.assertEqual(paths, [cfg_path.expanduser().resolve()])

    def test_global_config_path_prefers_xdg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            xdg = Path(td)
            config_file = xdg / "terok" / "config.yml"
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config_file.write_text("ui:\n  base_port: 7000\n", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg)}, clear=False):
                path = cfg.global_config_path()
                self.assertEqual(path, config_file.resolve())

    def test_state_root_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with unittest.mock.patch.dict(os.environ, {"TEROK_STATE_DIR": td}):
                self.assertEqual(cfg.state_root(), Path(td).resolve())

    def test_state_root_config_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            state_dir = Path(td) / "state"
            cfg_path.write_text(f"paths:\n  state_root: {state_dir}\n", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"TEROK_CONFIG_FILE": str(cfg_path)}):
                self.assertEqual(cfg.state_root(), state_dir.resolve())

    def test_user_projects_root_config_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            projects_dir = Path(td) / "projects"
            cfg_path.write_text(f"paths:\n  user_projects_root: {projects_dir}\n", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"TEROK_CONFIG_FILE": str(cfg_path)}):
                self.assertEqual(cfg.user_projects_root(), projects_dir.resolve())

    def test_ui_and_envs_values_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            envs_dir = Path(td) / "envs"
            cfg_path.write_text(
                f"ui:\n  base_port: 8123\nenvs:\n  base_dir: {envs_dir}\n",
                encoding="utf-8",
            )
            with unittest.mock.patch.dict(os.environ, {"TEROK_CONFIG_FILE": str(cfg_path)}):
                self.assertEqual(cfg.get_ui_base_port(), 8123)
                self.assertEqual(cfg.get_envs_base_dir(), envs_dir.resolve())

    def test_tui_default_tmux_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            cfg_path.write_text("tui:\n  default_tmux: true\n", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"TEROK_CONFIG_FILE": str(cfg_path)}):
                self.assertTrue(cfg.get_tui_default_tmux())

    def test_tui_default_tmux_default_false(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            cfg_path.write_text("", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"TEROK_CONFIG_FILE": str(cfg_path)}):
                self.assertFalse(cfg.get_tui_default_tmux())

    def test_tui_default_tmux_explicit_false(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            cfg_path.write_text("tui:\n  default_tmux: false\n", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"TEROK_CONFIG_FILE": str(cfg_path)}):
                self.assertFalse(cfg.get_tui_default_tmux())

    def test_experimental_default_false(self) -> None:
        cfg.set_experimental(False)
        self.assertFalse(cfg.is_experimental())

    def test_experimental_set_true(self) -> None:
        cfg.set_experimental(True)
        try:
            self.assertTrue(cfg.is_experimental())
        finally:
            cfg.set_experimental(False)

    def test_experimental_roundtrip(self) -> None:
        cfg.set_experimental(True)
        try:
            self.assertTrue(cfg.is_experimental())
        finally:
            cfg.set_experimental(False)
        self.assertFalse(cfg.is_experimental())


class GlobalConfigValidationTests(unittest.TestCase):
    """Tests for global config validation via _load_validated()."""

    def test_gate_server_port_from_config(self) -> None:
        """gate_server.port is read from validated config."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            cfg_path.write_text("gate_server:\n  port: 1234\n", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"TEROK_CONFIG_FILE": str(cfg_path)}):
                self.assertEqual(cfg.get_gate_server_port(), 1234)

    def test_invalid_config_falls_back_to_defaults(self) -> None:
        """Invalid global config falls back to defaults (doesn't crash)."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            # Use a non-default port (9999) so we can prove the typoed section is ignored
            # and the default (7860) is returned instead.
            cfg_path.write_text("uii:\n  base_port: 9999\n", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"TEROK_CONFIG_FILE": str(cfg_path)}):
                # Typoed key "uii" is rejected; fallback returns the real default 7860
                self.assertEqual(cfg.get_ui_base_port(), 7860)

    def test_logs_partial_streaming_from_config(self) -> None:
        """logs.partial_streaming is read from validated config."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            cfg_path.write_text("logs:\n  partial_streaming: false\n", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"TEROK_CONFIG_FILE": str(cfg_path)}):
                self.assertFalse(cfg.get_logs_partial_streaming())

    def test_task_name_categories_single_string(self) -> None:
        """tasks.name_categories coerces a single string to a list."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            cfg_path.write_text("tasks:\n  name_categories: animals\n", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"TEROK_CONFIG_FILE": str(cfg_path)}):
                self.assertEqual(cfg.get_task_name_categories(), ["animals"])


class ShieldBypassTests(unittest.TestCase):
    """Tests for get_shield_bypass_firewall_no_protection()."""

    def test_default_false(self) -> None:
        """Returns False when no shield config is set."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            cfg_path.write_text("", encoding="utf-8")
            with unittest.mock.patch.dict(os.environ, {"TEROK_CONFIG_FILE": str(cfg_path)}):
                self.assertFalse(cfg.get_shield_bypass_firewall_no_protection())

    def test_true_when_set(self) -> None:
        """Returns True when bypass_firewall_no_protection is set."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            cfg_path.write_text(
                "shield:\n  bypass_firewall_no_protection: true\n", encoding="utf-8"
            )
            with unittest.mock.patch.dict(os.environ, {"TEROK_CONFIG_FILE": str(cfg_path)}):
                self.assertTrue(cfg.get_shield_bypass_firewall_no_protection())

    def test_explicit_false(self) -> None:
        """Returns False when explicitly set to false."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yml"
            cfg_path.write_text(
                "shield:\n  bypass_firewall_no_protection: false\n", encoding="utf-8"
            )
            with unittest.mock.patch.dict(os.environ, {"TEROK_CONFIG_FILE": str(cfg_path)}):
                self.assertFalse(cfg.get_shield_bypass_firewall_no_protection())
