# SPDX-FileCopyrightText: 2025-2026 Jiri Vyskocil <jiri@vyskocil.com>
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the emoji display-width utility."""

import unittest

from luskctl.lib.util.emoji import draw_emoji


class TestDrawEmoji(unittest.TestCase):
    """Verify draw_emoji pads emojis to a consistent cell width."""

    def test_empty_string_returns_empty(self):
        """Empty input produces empty output."""
        self.assertEqual(draw_emoji(""), "")

    def test_none_returns_empty(self):
        """None input produces empty output."""
        self.assertEqual(draw_emoji(None), "")  # type: ignore[arg-type]

    def test_wide_emoji_no_padding(self):
        """A natively 2-cell-wide emoji (eaw=W) needs no padding."""
        self.assertEqual(draw_emoji("🚀"), "🚀")

    def test_narrow_char_gets_padded(self):
        """A 1-cell character gets padded to width 2."""
        self.assertEqual(draw_emoji("X"), "X ")

    def test_custom_width(self):
        """Custom width parameter is respected."""
        self.assertEqual(draw_emoji("X", width=4), "X   ")

    def test_emoji_wider_than_target(self):
        """Emoji wider than target width is returned unchanged."""
        self.assertEqual(draw_emoji("🚀", width=1), "🚀")

    def test_all_status_emojis_are_exactly_width_2(self):
        """All status emojis used by the project are exactly 2 cells wide."""
        from luskctl.lib.containers.task_display import STATUS_DISPLAY

        for status, info in STATUS_DISPLAY.items():
            self.assertEqual(
                draw_emoji(info.emoji),
                info.emoji,
                f"Status emoji for {status!r} should not need padding",
            )
            self.assertEqual(
                draw_emoji(info.emoji, width=3),
                f"{info.emoji} ",
                f"Status emoji for {status!r} should be exactly 2 cells wide",
            )

    def test_all_mode_emojis_are_exactly_width_2(self):
        """All mode emojis used by the project are exactly 2 cells wide."""
        from luskctl.lib.containers.task_display import MODE_DISPLAY

        for mode, info in MODE_DISPLAY.items():
            self.assertEqual(
                draw_emoji(info.emoji),
                info.emoji,
                f"Mode emoji for {mode!r} should not need padding",
            )
            self.assertEqual(
                draw_emoji(info.emoji, width=3),
                f"{info.emoji} ",
                f"Mode emoji for {mode!r} should be exactly 2 cells wide",
            )

    def test_all_backend_emojis_are_exactly_width_2(self):
        """All web backend emojis are exactly 2 cells wide."""
        from luskctl.lib.containers.task_display import (
            WEB_BACKEND_DEFAULT_EMOJI,
            WEB_BACKEND_EMOJI,
        )

        for backend, emoji in WEB_BACKEND_EMOJI.items():
            self.assertEqual(
                draw_emoji(emoji),
                emoji,
                f"Backend emoji for {backend!r} should not need padding",
            )
            self.assertEqual(
                draw_emoji(emoji, width=3),
                f"{emoji} ",
                f"Backend emoji for {backend!r} should be exactly 2 cells wide",
            )
        self.assertEqual(draw_emoji(WEB_BACKEND_DEFAULT_EMOJI), WEB_BACKEND_DEFAULT_EMOJI)
        self.assertEqual(
            draw_emoji(WEB_BACKEND_DEFAULT_EMOJI, width=3),
            f"{WEB_BACKEND_DEFAULT_EMOJI} ",
        )


if __name__ == "__main__":
    unittest.main()
