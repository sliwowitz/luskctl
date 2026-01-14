"""Tests for version and branch detection functionality."""

import sys
import tempfile
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


class BuildScriptTests(unittest.TestCase):
    """Test build_script.py functionality."""

    def setUp(self) -> None:
        """Add build_script.py to the path."""
        # Add the repo root to the path so we can import build_script
        repo_root = Path(__file__).parent.parent.parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))

    def test_is_tagged_release_with_version_tag(self) -> None:
        """Test that _is_tagged_release detects version tags correctly."""
        import build_script

        # Mock git describe to return a version tag
        with mock.patch("subprocess.run") as mock_run:
            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "v1.2.3"
            mock_run.return_value = mock_result

            self.assertTrue(build_script._is_tagged_release())

    def test_is_tagged_release_with_non_version_tag(self) -> None:
        """Test that _is_tagged_release rejects non-version tags."""
        import build_script

        # Mock git describe to return a non-version tag
        with mock.patch("subprocess.run") as mock_run:
            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "versioninfo"  # Not a version tag
            mock_run.return_value = mock_result

            self.assertFalse(build_script._is_tagged_release())

    def test_is_tagged_release_with_valid_tag_v_prefix(self) -> None:
        """Test tag validation with 'v' prefix followed by digit."""
        import build_script

        with mock.patch("subprocess.run") as mock_run:
            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "v0.3.1"
            mock_run.return_value = mock_result

            self.assertTrue(build_script._is_tagged_release())

    def test_is_tagged_release_rejects_v_only(self) -> None:
        """Test that 'v' alone is not considered a version tag."""
        import build_script

        with mock.patch("subprocess.run") as mock_run:
            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "v"  # Just 'v' without digit
            mock_run.return_value = mock_result

            self.assertFalse(build_script._is_tagged_release())

    def test_is_tagged_release_not_at_tag(self) -> None:
        """Test that _is_tagged_release returns False when not at a tag."""
        import build_script

        # Mock git describe to fail (not at a tag)
        with mock.patch("subprocess.run") as mock_run:
            mock_result = mock.MagicMock()
            mock_result.returncode = 1
            mock_run.return_value = mock_result

            self.assertFalse(build_script._is_tagged_release())

    def test_get_git_branch(self) -> None:
        """Test that _get_git_branch detects branch name correctly."""
        import build_script

        # Mock git commands
        with mock.patch("subprocess.run") as mock_run:
            # First call: git rev-parse --is-inside-work-tree
            rev_parse_result = mock.MagicMock()
            rev_parse_result.returncode = 0
            rev_parse_result.stdout = "true"

            # Second call: git branch --show-current
            branch_result = mock.MagicMock()
            branch_result.returncode = 0
            branch_result.stdout = "main"

            mock_run.side_effect = [rev_parse_result, branch_result]

            branch = build_script._get_git_branch()

            self.assertEqual(branch, "main")

    def test_get_git_branch_not_in_repo(self) -> None:
        """Test that _get_git_branch returns None when not in a git repo."""
        import build_script

        # Mock git rev-parse to fail (not in a repo)
        with mock.patch("subprocess.run") as mock_run:
            mock_result = mock.MagicMock()
            mock_result.returncode = 1
            mock_run.return_value = mock_result

            branch = build_script._get_git_branch()

            self.assertIsNone(branch)

    def test_get_git_branch_detached_head(self) -> None:
        """Test that _get_git_branch returns None in detached HEAD state."""
        import build_script

        # Mock git commands for detached HEAD (empty branch name)
        with mock.patch("subprocess.run") as mock_run:
            # First call: git rev-parse --is-inside-work-tree
            rev_parse_result = mock.MagicMock()
            rev_parse_result.returncode = 0
            rev_parse_result.stdout = "true"

            # Second call: git branch --show-current (empty in detached HEAD)
            branch_result = mock.MagicMock()
            branch_result.returncode = 0
            branch_result.stdout = ""

            mock_run.side_effect = [rev_parse_result, branch_result]

            branch = build_script._get_git_branch()

            self.assertIsNone(branch)

    def test_write_branch_info_escapes_special_characters(self) -> None:
        """Test that _write_branch_info properly escapes branch names."""
        import build_script

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create src/luskctl directory structure
            src_dir = Path(tmpdir) / "src" / "luskctl"
            src_dir.mkdir(parents=True)

            # Change to tmpdir for the test
            import os

            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                # Test with a branch name containing quotes and backslashes
                branch_name = 'feature/"test"\\branch'
                build_script._write_branch_info(branch_name)

                # Read the generated file
                branch_info_path = src_dir / "_branch_info.py"
                content = branch_info_path.read_text()

                # Verify that the branch name is properly escaped using repr()
                self.assertIn("BRANCH_NAME = 'feature/\"test\"\\\\branch'", content)

            finally:
                os.chdir(original_cwd)

    def test_write_branch_info_simple_branch(self) -> None:
        """Test that _write_branch_info works with simple branch names."""
        import build_script

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create src/luskctl directory structure
            src_dir = Path(tmpdir) / "src" / "luskctl"
            src_dir.mkdir(parents=True)

            # Change to tmpdir for the test
            import os

            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                # Test with a simple branch name
                branch_name = "main"
                build_script._write_branch_info(branch_name)

                # Read the generated file
                branch_info_path = src_dir / "_branch_info.py"
                content = branch_info_path.read_text()

                # Verify the content
                self.assertIn("BRANCH_NAME = 'main'", content)
                self.assertIn("# Auto-generated by build_script.py", content)

            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
