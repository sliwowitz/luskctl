# SPDX-FileCopyrightText: 2025-2026 Jiri Vyskocil <jiri@vyskocil.com>
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for agent instruction resolution module."""

import unittest

from luskctl.lib.containers.instructions import (
    bundled_default_instructions,
    has_custom_instructions,
    resolve_instructions,
)


class BundledDefaultTests(unittest.TestCase):
    """Tests for bundled default instructions."""

    def test_bundled_default_exists(self) -> None:
        """Bundled default instructions are non-empty and readable."""
        text = bundled_default_instructions()
        self.assertIsInstance(text, str)
        self.assertTrue(len(text) > 100)
        self.assertIn("luskctl", text)

    def test_bundled_default_contains_key_sections(self) -> None:
        """Bundled default mentions workspace, git, and sudo."""
        text = bundled_default_instructions()
        self.assertIn("/workspace/", text)
        self.assertIn("sudo", text)
        self.assertIn("git", text.lower())


class ResolveInstructionsTests(unittest.TestCase):
    """Tests for resolve_instructions()."""

    def test_flat_string(self) -> None:
        """Flat string instructions are returned as-is."""
        config = {"instructions": "Do the thing."}
        result = resolve_instructions(config, "claude")
        self.assertEqual(result, "Do the thing.")

    def test_per_provider_dict(self) -> None:
        """Per-provider dict selects the right provider value."""
        config = {
            "instructions": {
                "claude": "Claude instructions",
                "codex": "Codex instructions",
                "_default": "Default instructions",
            }
        }
        self.assertEqual(resolve_instructions(config, "claude"), "Claude instructions")
        self.assertEqual(resolve_instructions(config, "codex"), "Codex instructions")

    def test_per_provider_dict_fallback_to_default(self) -> None:
        """Per-provider dict falls back to _default for unknown provider."""
        config = {
            "instructions": {
                "claude": "Claude instructions",
                "_default": "Default instructions",
            }
        }
        self.assertEqual(resolve_instructions(config, "vibe"), "Default instructions")

    def test_per_provider_dict_no_match_returns_bundled(self) -> None:
        """Per-provider dict with no match and no _default returns bundled default."""
        config = {"instructions": {"claude": "Claude only"}}
        result = resolve_instructions(config, "codex")
        # Should fall back to bundled default
        self.assertIn("luskctl", result)

    def test_fallback_to_default(self) -> None:
        """Absent key returns bundled default."""
        config = {}
        result = resolve_instructions(config, "claude")
        self.assertIn("luskctl", result)

    def test_null_uses_default(self) -> None:
        """Explicit None value returns bundled default."""
        config = {"instructions": None}
        result = resolve_instructions(config, "claude")
        self.assertIn("luskctl", result)

    def test_list_joined(self) -> None:
        """List of strings is joined with double newlines."""
        config = {"instructions": ["First part.", "Second part.", "Third part."]}
        result = resolve_instructions(config, "claude")
        self.assertEqual(result, "First part.\n\nSecond part.\n\nThird part.")

    def test_list_with_inherit_stripped(self) -> None:
        """_inherit sentinel is stripped from lists."""
        config = {"instructions": ["Base text.", "_inherit", "Extra text."]}
        result = resolve_instructions(config, "claude")
        self.assertEqual(result, "Base text.\n\nExtra text.")


class HasCustomInstructionsTests(unittest.TestCase):
    """Tests for has_custom_instructions()."""

    def test_true_when_present(self) -> None:
        """Returns True when instructions key is present."""
        self.assertTrue(has_custom_instructions({"instructions": "Custom"}))

    def test_false_when_absent(self) -> None:
        """Returns False when instructions key is absent."""
        self.assertFalse(has_custom_instructions({}))

    def test_false_when_none(self) -> None:
        """Returns False when instructions is explicitly None."""
        self.assertFalse(has_custom_instructions({"instructions": None}))

    def test_true_for_dict_form(self) -> None:
        """Returns True for per-provider dict form."""
        self.assertTrue(has_custom_instructions({"instructions": {"claude": "Custom"}}))

    def test_true_for_list_form(self) -> None:
        """Returns True for list form."""
        self.assertTrue(has_custom_instructions({"instructions": ["Part 1", "Part 2"]}))


if __name__ == "__main__":
    unittest.main()
