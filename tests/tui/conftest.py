"""Add tests/tui/ to sys.path so tui_test_helpers is importable."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
