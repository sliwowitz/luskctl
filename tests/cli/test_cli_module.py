from __future__ import annotations

import importlib
import unittest


class CliModuleTests(unittest.TestCase):
    def test_cli_main_is_callable(self) -> None:
        module = importlib.import_module("codexctl.cli.main")
        self.assertTrue(callable(getattr(module, "main", None)))
