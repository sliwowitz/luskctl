import importlib
import unittest


class TuiModuleTests(unittest.TestCase):
    def test_tui_main_is_callable(self) -> None:
        module = importlib.import_module("codexctl.tui.app")
        self.assertTrue(callable(getattr(module, "main", None)))
