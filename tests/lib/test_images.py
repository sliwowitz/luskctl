from __future__ import annotations

import unittest

from codexctl.lib import images


class ImagesTests(unittest.TestCase):
    """Tests for the images module."""

    # Tests for _base_tag function
    def test_base_tag_empty_string(self) -> None:
        """Empty string should return default tag."""
        result = images._base_tag("")
        self.assertEqual(result, "ubuntu-24.04")

    def test_base_tag_none(self) -> None:
        """None should return default tag."""
        result = images._base_tag(None)  # type: ignore
        self.assertEqual(result, "ubuntu-24.04")

    def test_base_tag_whitespace_only(self) -> None:
        """Whitespace-only string should return default tag."""
        result = images._base_tag("   ")
        self.assertEqual(result, "ubuntu-24.04")

    def test_base_tag_simple_valid_name(self) -> None:
        """Simple valid name should be normalized."""
        result = images._base_tag("ubuntu-22.04")
        self.assertEqual(result, "ubuntu-22.04")

    def test_base_tag_uppercase_converted(self) -> None:
        """Uppercase should be converted to lowercase."""
        result = images._base_tag("Ubuntu-22.04")
        self.assertEqual(result, "ubuntu-22.04")

    def test_base_tag_special_characters_sanitized(self) -> None:
        """Special characters should be replaced with hyphens."""
        result = images._base_tag("ubuntu@22#04")
        self.assertEqual(result, "ubuntu-22-04")

    def test_base_tag_multiple_special_chars(self) -> None:
        """Multiple special characters should be replaced."""
        result = images._base_tag("test@#$%^&*()image")
        self.assertEqual(result, "test-image")

    def test_base_tag_leading_trailing_special_chars(self) -> None:
        """Leading/trailing dots and hyphens should be stripped."""
        result = images._base_tag("--ubuntu-22.04--")
        self.assertEqual(result, "ubuntu-22.04")

    def test_base_tag_dots_preserved(self) -> None:
        """Dots in valid positions should be preserved."""
        result = images._base_tag("ubuntu.22.04")
        self.assertEqual(result, "ubuntu.22.04")

    def test_base_tag_underscores_preserved(self) -> None:
        """Underscores should be preserved."""
        result = images._base_tag("ubuntu_22_04")
        self.assertEqual(result, "ubuntu_22_04")

    def test_base_tag_mixed_valid_chars(self) -> None:
        """Mixed valid characters should be preserved."""
        result = images._base_tag("ubuntu-22.04_LTS")
        self.assertEqual(result, "ubuntu-22.04_lts")

    def test_base_tag_only_special_chars(self) -> None:
        """String with only special characters should return default."""
        result = images._base_tag("@#$%^&*()")
        self.assertEqual(result, "ubuntu-24.04")

    def test_base_tag_long_name_under_limit(self) -> None:
        """Long name under 120 chars should not be truncated."""
        name = "a" * 120
        result = images._base_tag(name)
        self.assertEqual(result, name)
        self.assertEqual(len(result), 120)

    def test_base_tag_long_name_over_limit(self) -> None:
        """Long name over 120 chars should be truncated with hash."""
        name = "a" * 121
        result = images._base_tag(name)
        # Should be 111 chars + "-" + 8 char hash = 120 total
        self.assertEqual(len(result), 120)
        self.assertTrue(result.startswith("a" * 111))
        self.assertTrue("-" in result[111:])
        # Check hash is alphanumeric
        hash_part = result.split("-")[-1]
        self.assertEqual(len(hash_part), 8)
        self.assertTrue(hash_part.isalnum())

    def test_base_tag_long_name_consistent_hash(self) -> None:
        """Same long name should produce same hash."""
        name = "b" * 150
        result1 = images._base_tag(name)
        result2 = images._base_tag(name)
        self.assertEqual(result1, result2)

    def test_base_tag_long_name_different_hash(self) -> None:
        """Different long names should produce different hashes."""
        name1 = "c" * 150
        name2 = "d" * 150
        result1 = images._base_tag(name1)
        result2 = images._base_tag(name2)
        self.assertNotEqual(result1, result2)

    def test_base_tag_long_with_special_chars(self) -> None:
        """Long name with special chars should be sanitized then truncated."""
        name = ("ubuntu@special" * 20)  # Over 120 chars with special chars
        result = images._base_tag(name)
        self.assertEqual(len(result), 120)
        # Should not contain @ symbols
        self.assertNotIn("@", result)

    # Tests for image naming functions
    def test_base_dev_image(self) -> None:
        """base_dev_image should return correct L0 image name."""
        result = images.base_dev_image("ubuntu-22.04")
        self.assertEqual(result, "codexctl-l0:ubuntu-22.04")

    def test_base_dev_image_with_special_chars(self) -> None:
        """base_dev_image should sanitize base_image."""
        result = images.base_dev_image("ubuntu@22.04")
        self.assertEqual(result, "codexctl-l0:ubuntu-22.04")

    def test_agent_cli_image(self) -> None:
        """agent_cli_image should return correct L1 CLI image name."""
        result = images.agent_cli_image("ubuntu-22.04")
        self.assertEqual(result, "codexctl-l1-cli:ubuntu-22.04")

    def test_agent_cli_image_with_special_chars(self) -> None:
        """agent_cli_image should sanitize base_image."""
        result = images.agent_cli_image("ubuntu@22.04")
        self.assertEqual(result, "codexctl-l1-cli:ubuntu-22.04")

    def test_agent_ui_image(self) -> None:
        """agent_ui_image should return correct L1 UI image name."""
        result = images.agent_ui_image("ubuntu-22.04")
        self.assertEqual(result, "codexctl-l1-ui:ubuntu-22.04")

    def test_agent_ui_image_with_special_chars(self) -> None:
        """agent_ui_image should sanitize base_image."""
        result = images.agent_ui_image("ubuntu@22.04")
        self.assertEqual(result, "codexctl-l1-ui:ubuntu-22.04")

    def test_project_cli_image(self) -> None:
        """project_cli_image should return correct L2 CLI image name."""
        result = images.project_cli_image("my-project")
        self.assertEqual(result, "my-project:l2-cli")

    def test_project_ui_image(self) -> None:
        """project_ui_image should return correct L2 UI image name."""
        result = images.project_ui_image("my-project")
        self.assertEqual(result, "my-project:l2-ui")

    def test_project_dev_image(self) -> None:
        """project_dev_image should return correct L2 dev image name."""
        result = images.project_dev_image("my-project")
        self.assertEqual(result, "my-project:l2-dev")

    def test_all_functions_with_empty_base_image(self) -> None:
        """All base_image functions should handle empty string."""
        self.assertEqual(images.base_dev_image(""), "codexctl-l0:ubuntu-24.04")
        self.assertEqual(images.agent_cli_image(""), "codexctl-l1-cli:ubuntu-24.04")
        self.assertEqual(images.agent_ui_image(""), "codexctl-l1-ui:ubuntu-24.04")

    def test_all_functions_with_long_base_image(self) -> None:
        """All base_image functions should handle long names."""
        long_name = "x" * 150
        # All should produce 120-char tags
        base_dev = images.base_dev_image(long_name)
        agent_cli = images.agent_cli_image(long_name)
        agent_ui = images.agent_ui_image(long_name)
        
        # Extract tags (after the colon)
        base_dev_tag = base_dev.split(":")[1]
        agent_cli_tag = agent_cli.split(":")[1]
        agent_ui_tag = agent_ui.split(":")[1]
        
        self.assertEqual(len(base_dev_tag), 120)
        self.assertEqual(len(agent_cli_tag), 120)
        self.assertEqual(len(agent_ui_tag), 120)
        
        # All should use the same tag
        self.assertEqual(base_dev_tag, agent_cli_tag)
        self.assertEqual(agent_cli_tag, agent_ui_tag)


if __name__ == "__main__":
    unittest.main()
