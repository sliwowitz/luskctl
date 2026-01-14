import importlib
import os
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace


class CliConfigOutputTests(unittest.TestCase):
    def test_config_command_color_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            global_cfg = base / "global.yml"
            global_cfg.write_text("ui:\n  base_port: 7777\n", encoding="utf-8")

            user_root = base / "user-projects"
            system_root = base / "system-projects"
            state_root = base / "state"
            build_root = base / "build"
            envs_root = base / "envs"
            user_root.mkdir(parents=True, exist_ok=True)
            system_root.mkdir(parents=True, exist_ok=True)
            state_root.mkdir(parents=True, exist_ok=True)
            build_root.mkdir(parents=True, exist_ok=True)
            envs_root.mkdir(parents=True, exist_ok=True)

            resources_root = base / "pkg"
            templates_dir = resources_root / "resources" / "templates"
            scripts_dir = resources_root / "resources" / "scripts"
            templates_dir.mkdir(parents=True, exist_ok=True)
            scripts_dir.mkdir(parents=True, exist_ok=True)
            (templates_dir / "l0.template").write_text("", encoding="utf-8")
            (scripts_dir / "script.sh").write_text("", encoding="utf-8")

            project_root = base / "proj-alpha"
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / "project.yml").write_text("project:\n  id: alpha\n", encoding="utf-8")
            build_file = build_root / "alpha" / "L0.Dockerfile"
            build_file.parent.mkdir(parents=True, exist_ok=True)
            build_file.write_text("", encoding="utf-8")

            buffer = StringIO()
            with (
                unittest.mock.patch.dict(
                    os.environ,
                    {"LUSKCTL_CONFIG_FILE": str(global_cfg)},
                    clear=True,
                ),
                unittest.mock.patch.object(sys, "argv", ["luskctl", "config"]),
                unittest.mock.patch("luskctl.cli.main._supports_color", return_value=True),
                unittest.mock.patch(
                    "luskctl.cli.main._global_config_path",
                    return_value=global_cfg,
                ),
                unittest.mock.patch(
                    "luskctl.cli.main._global_config_search_paths",
                    return_value=[global_cfg],
                ),
                unittest.mock.patch(
                    "luskctl.cli.main._get_ui_base_port",
                    return_value=7777,
                ),
                unittest.mock.patch(
                    "luskctl.cli.main._get_envs_base_dir",
                    return_value=envs_root,
                ),
                unittest.mock.patch(
                    "luskctl.cli.main._user_projects_root",
                    return_value=user_root,
                ),
                unittest.mock.patch(
                    "luskctl.cli.main._config_root",
                    return_value=system_root,
                ),
                unittest.mock.patch(
                    "luskctl.cli.main._state_root",
                    return_value=state_root,
                ),
                unittest.mock.patch(
                    "luskctl.cli.main._build_root",
                    return_value=build_root,
                ),
                unittest.mock.patch(
                    "luskctl.cli.main.list_projects",
                    return_value=[SimpleNamespace(id="alpha", root=project_root)],
                ),
                unittest.mock.patch(
                    "luskctl.cli.main.resources.files",
                    return_value=resources_root,
                ),
                redirect_stdout(buffer),
            ):
                importlib.import_module("luskctl.cli.main").main()

            output = buffer.getvalue()
            self.assertIn("\x1b[32myes\x1b[0m", output)
            self.assertIn("\x1b[35malpha\x1b[0m", output)
            self.assertIn(f"\x1b[90m{project_root / 'project.yml'}\x1b[0m", output)
            self.assertIn(f"\x1b[90m{templates_dir}\x1b[0m", output)
            self.assertIn("\x1b[90mscript.sh\x1b[0m", output)
            self.assertIn(
                f"- LUSKCTL_CONFIG_FILE=\x1b[90m{global_cfg}\x1b[0m",
                output,
            )
            self.assertIn(
                f"- State root: \x1b[90m{state_root}\x1b[0m (exists: \x1b[32myes\x1b[0m)",
                output,
            )
