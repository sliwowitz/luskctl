"""
Simple tests for the opencode-custom script functionality.
"""

import unittest
from pathlib import Path


class OpenCodeCustomSimpleTests(unittest.TestCase):
    """Simple tests for opencode-custom script functionality."""

    def test_script_syntax(self) -> None:
        """Test that the script has valid Python syntax."""
        script_path = Path(__file__).parent.parent.parent / "src" / "luskctl" / "resources" / "scripts" / "opencode-custom"

        with open(script_path) as f:
            code = f.read()

        # This will raise SyntaxError if there are syntax issues
        compile(code, str(script_path), "exec")

    def test_shared_module_syntax(self) -> None:
        """Test that the shared module has valid Python syntax."""
        module_path = Path(__file__).parent.parent.parent / "src" / "luskctl" / "resources" / "scripts" / "opencode_common.py"

        with open(module_path) as f:
            code = f.read()

        # This will raise SyntaxError if there are syntax issues
        compile(code, str(module_path), "exec")

    def test_blablador_syntax(self) -> None:
        """Test that the updated blablador script has valid Python syntax."""
        script_path = Path(__file__).parent.parent.parent / "src" / "luskctl" / "resources" / "scripts" / "blablador"

        with open(script_path) as f:
            code = f.read()

        # This will raise SyntaxError if there are syntax issues
        compile(code, str(script_path), "exec")


if __name__ == "__main__":
    unittest.main()
