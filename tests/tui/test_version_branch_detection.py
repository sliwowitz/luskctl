"""Tests for version and branch detection functionality."""

import json
import unittest
from pathlib import Path
from unittest import mock


class VersionDetectionTests(unittest.TestCase):
    """Test version detection in __init__.py."""

    def test_version_attribute_exists(self) -> None:
        """Test that __version__ attribute exists and is a string."""
        import luskctl

        self.assertTrue(hasattr(luskctl, "__version__"))
        self.assertIsInstance(luskctl.__version__, str)
        self.assertNotEqual(luskctl.__version__, "")

    def test_version_uses_importlib_metadata(self) -> None:
        """Test that version can be retrieved from importlib.metadata."""
        from importlib.metadata import version

        # This should work when the package is installed
        pkg_version = version("luskctl")
        self.assertIsInstance(pkg_version, str)
        self.assertNotEqual(pkg_version, "")


class VersionModuleTests(unittest.TestCase):
    """Test luskctl.lib.version module."""

    def test_format_version_string_with_branch(self) -> None:
        """Test format_version_string with a branch name."""
        from luskctl.lib.version import format_version_string

        result = format_version_string("1.2.3", "feature-branch")
        self.assertEqual(result, "1.2.3 [feature-branch]")

    def test_format_version_string_without_branch(self) -> None:
        """Test format_version_string without a branch name."""
        from luskctl.lib.version import format_version_string

        result = format_version_string("1.2.3", None)
        self.assertEqual(result, "1.2.3")

    def test_get_version_info_returns_tuple(self) -> None:
        """Test that get_version_info returns a tuple of (version, branch)."""
        from luskctl.lib.version import get_version_info

        result = get_version_info()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        version, branch = result
        self.assertIsInstance(version, str)
        self.assertTrue(branch is None or isinstance(branch, str))

    def test_get_version_info_without_branch_data(self) -> None:
        """Test get_version_info when no branch data is available."""
        # Mock subprocess to fail git detection (simulating tarball install)
        with mock.patch("luskctl.lib.version.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("git not found")

            from luskctl.lib.version import get_version_info

            with mock.patch("luskctl.lib.version._get_pep610_revision", return_value=None):
                _, branch = get_version_info()
            # Branch should be None when PEP 610 is absent and git detection fails
            self.assertIsNone(branch)


class Pep610Tests(unittest.TestCase):
    """Test PEP 610 direct_url.json handling."""

    def test_pep610_requested_revision(self) -> None:
        """Use requested_revision when present."""
        from luskctl.lib.version import _get_pep610_revision

        direct_url = json.dumps({"vcs_info": {"requested_revision": "feature/foo"}})
        dist = mock.MagicMock()
        dist.read_text.return_value = direct_url

        with mock.patch("luskctl.lib.version.metadata.distribution", return_value=dist):
            self.assertEqual(_get_pep610_revision(), "feature/foo")

    def test_pep610_commit_id_fallback(self) -> None:
        """Fallback to commit_id when requested_revision is missing."""
        from luskctl.lib.version import _get_pep610_revision

        direct_url = json.dumps({"vcs_info": {"commit_id": "abc123"}})
        dist = mock.MagicMock()
        dist.read_text.return_value = direct_url

        with mock.patch("luskctl.lib.version.metadata.distribution", return_value=dist):
            self.assertEqual(_get_pep610_revision(), "abc123")


class CLIVersionTests(unittest.TestCase):
    """Test CLI --version flag."""

    def test_cli_version_flag(self) -> None:
        """Test that luskctl --version outputs version info."""
        import subprocess

        result = subprocess.run(
            ["python", "-m", "luskctl.cli.main", "--version"],
            capture_output=True,
            text=True,
        )
        # --version exits with code 0
        self.assertEqual(result.returncode, 0)
        # Output should contain "luskctl" and version number
        self.assertIn("luskctl", result.stdout)
        # Should have some version-like string
        self.assertRegex(result.stdout, r"\d+\.\d+")

    def test_cli_version_matches_module_version(self) -> None:
        """Test that CLI --version matches the module version."""
        import subprocess

        from luskctl.lib.version import format_version_string, get_version_info

        version, branch = get_version_info()
        expected_version_str = format_version_string(version, branch)

        result = subprocess.run(
            ["python", "-m", "luskctl.cli.main", "--version"],
            capture_output=True,
            text=True,
        )
        self.assertIn(expected_version_str, result.stdout)


class BranchInfoPlaceholderTests(unittest.TestCase):
    """Test that _branch_info.py placeholder is correctly set."""

    def test_branch_info_placeholder_is_none(self) -> None:
        """Test that the committed _branch_info.py has BRANCH_NAME = None."""
        branch_info_path = (
            Path(__file__).parent.parent.parent / "src" / "luskctl" / "_branch_info.py"
        )
        content = branch_info_path.read_text()
        # The placeholder should have BRANCH_NAME = None
        self.assertIn("BRANCH_NAME = None", content)


if __name__ == "__main__":
    unittest.main()
