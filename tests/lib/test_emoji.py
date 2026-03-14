# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Tests for the emoji display-width utility."""

from rich.cells import cell_len

from terok.lib.util.emoji import is_emoji_enabled, render_emoji, set_emoji_enabled


class _FakeInfo:
    """Minimal object satisfying the EmojiInfo protocol."""

    def __init__(self, emoji: str, label: str) -> None:
        self.emoji = emoji
        self.label = label


def _emoji_is_width_2(emoji: str) -> bool:
    """Return True if *emoji* is natively 2 cells wide (no padding needed)."""
    return cell_len(emoji) == 2


class TestRenderEmoji:
    """Verify render_emoji returns the emoji from info objects."""

    def setup_method(self, method: object):
        """Ensure emoji mode is enabled for each test."""
        set_emoji_enabled(True)

    def teardown_method(self, method: object):
        """Reset emoji mode after each test."""
        set_emoji_enabled(True)

    def test_returns_emoji_from_info(self):
        """render_emoji returns the emoji attribute."""
        info = _FakeInfo("\U0001f680", "rocket")
        assert render_emoji(info) == "\U0001f680"

    def test_empty_emoji_returns_empty(self):
        """Empty emoji string produces empty output."""
        info = _FakeInfo("", "nothing")
        assert render_emoji(info) == ""

    def test_all_status_emojis_are_exactly_width_2(self):
        """All status emojis used by the project are exactly 2 cells wide."""
        from terok.lib.containers.task_display import STATUS_DISPLAY

        for _status, info in STATUS_DISPLAY.items():
            assert _emoji_is_width_2(info.emoji)

    def test_all_mode_emojis_are_exactly_width_2(self):
        """All mode emojis used by the project are exactly 2 cells wide."""
        from terok.lib.containers.task_display import MODE_DISPLAY

        for _mode, info in MODE_DISPLAY.items():
            assert _emoji_is_width_2(info.emoji)

    def test_all_backend_emojis_are_exactly_width_2(self):
        """All web backend emojis are exactly 2 cells wide."""
        from terok.lib.containers.task_display import WEB_BACKEND_DEFAULT, WEB_BACKEND_DISPLAY

        for _backend, info in WEB_BACKEND_DISPLAY.items():
            assert _emoji_is_width_2(info.emoji)
        assert _emoji_is_width_2(WEB_BACKEND_DEFAULT.emoji)

    def test_all_security_class_emojis_are_exactly_width_2(self):
        """All security class emojis are exactly 2 cells wide."""
        from terok.lib.containers.task_display import SECURITY_CLASS_DISPLAY

        for _key, badge in SECURITY_CLASS_DISPLAY.items():
            assert _emoji_is_width_2(badge.emoji)

    def test_all_gpu_emojis_are_exactly_width_2(self):
        """All GPU display emojis are exactly 2 cells wide."""
        from terok.lib.containers.task_display import GPU_DISPLAY

        for _key, badge in GPU_DISPLAY.items():
            assert _emoji_is_width_2(badge.emoji)

    def test_all_work_status_emojis_are_exactly_width_2(self):
        """All work status emojis are exactly 2 cells wide."""
        from terok.lib.containers.work_status import WORK_STATUS_DISPLAY

        for _key, info in WORK_STATUS_DISPLAY.items():
            assert _emoji_is_width_2(info.emoji)


class TestNoEmojiMode:
    """Verify render_emoji returns text labels when emoji mode is disabled."""

    def setup_method(self, method: object):
        """Disable emoji mode for these tests."""
        set_emoji_enabled(False)

    def teardown_method(self, method: object):
        """Re-enable emoji mode after tests."""
        set_emoji_enabled(True)

    def test_is_emoji_enabled_false(self):
        """is_emoji_enabled reflects the current state."""
        assert not is_emoji_enabled()

    def test_no_emoji_returns_label(self):
        """With emoji disabled, returns [label]."""
        info = _FakeInfo("\U0001f680", "rocket")
        assert render_emoji(info) == "[rocket]"

    def test_no_emoji_empty_label_returns_empty(self):
        """With emoji disabled and empty label, returns empty string."""
        info = _FakeInfo("\U0001f680", "")
        assert render_emoji(info) == ""

    def test_set_emoji_enabled_toggle(self):
        """Toggling emoji mode changes render_emoji behavior."""
        info = _FakeInfo("\U0001f680", "rocket")
        set_emoji_enabled(True)
        assert is_emoji_enabled()
        assert render_emoji(info) == "\U0001f680"

        set_emoji_enabled(False)
        assert not is_emoji_enabled()
        assert render_emoji(info) == "[rocket]"

    def test_all_status_display_has_labels(self):
        """All STATUS_DISPLAY entries have non-empty labels for no-emoji mode."""
        from terok.lib.containers.task_display import STATUS_DISPLAY

        for _status, info in STATUS_DISPLAY.items():
            assert info.label

    def test_all_mode_display_has_labels(self):
        """All MODE_DISPLAY entries have labels (empty is OK for None mode)."""
        from terok.lib.containers.task_display import MODE_DISPLAY

        for mode, info in MODE_DISPLAY.items():
            if mode is not None:
                assert info.label

    def test_all_backend_display_has_labels(self):
        """All WEB_BACKEND_DISPLAY entries have non-empty labels."""
        from terok.lib.containers.task_display import WEB_BACKEND_DISPLAY

        for _backend, info in WEB_BACKEND_DISPLAY.items():
            assert info.label

    def test_all_security_class_display_has_labels(self):
        """All SECURITY_CLASS_DISPLAY entries have non-empty labels."""
        from terok.lib.containers.task_display import SECURITY_CLASS_DISPLAY

        for _key, badge in SECURITY_CLASS_DISPLAY.items():
            assert badge.label

    def test_all_gpu_display_has_labels(self):
        """All GPU_DISPLAY entries have non-empty labels."""
        from terok.lib.containers.task_display import GPU_DISPLAY

        for _key, badge in GPU_DISPLAY.items():
            assert badge.label

    def test_all_work_status_display_has_labels(self):
        """All WORK_STATUS_DISPLAY entries have non-empty labels."""
        from terok.lib.containers.work_status import WORK_STATUS_DISPLAY

        for _key, info in WORK_STATUS_DISPLAY.items():
            assert info.label
