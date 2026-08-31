# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Verify SSH key routing labels, mutation guards, and minting shortcuts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest
from textual.app import App

from terok.lib.api.ssh_routing import KeyRouting
from terok.tui import key_routing_screen
from terok.tui.key_routing_screen import (
    KeyInventoryScreen,
    KeyRoutingScreen,
    _BaseRoutingScreen,
    _hint,
    _inventory_label,
    _key_label,
    _ProjectPickerScreen,
)


def _row(*, comment: str = "", key_type: str = "ed25519", fingerprint: str = "SHA256:abcdef"):
    """A stand-in key row carrying the fields the label helpers read."""
    return SimpleNamespace(comment=comment, key_type=key_type, fingerprint=fingerprint)


class _RoutingHost(App[None]):
    """Run the routing screen in the smallest app that can exercise its bindings."""

    def on_mount(self) -> None:
        """Open the routing screen."""
        self.push_screen(KeyRoutingScreen())


@pytest.fixture
def mint_calls(monkeypatch):
    """Serve one routed key and record every project passed to the minting API."""
    key = SimpleNamespace(
        id=1,
        comment="tk-main:alpha",
        key_type="ed25519",
        fingerprint="SHA256:abcdef",
    )
    routing = KeyRouting(
        keys=(key,),
        projects=("alpha", "beta"),
        links=frozenset({("alpha", key.id)}),
    )
    calls: list[str] = []
    monkeypatch.setattr(key_routing_screen, "load_key_routing", lambda: routing)
    monkeypatch.setattr(key_routing_screen, "mint_key", calls.append)
    return calls


class TestMintShortcuts:
    """Every advertised ``n`` path reaches the project-scoped minting API."""

    @pytest.mark.asyncio
    async def test_matrix_mints_for_cursor_project(self, mint_calls) -> None:
        """Matrix mode derives the project from the cursor column."""
        app = _RoutingHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

        assert mint_calls == ["alpha"]

    @pytest.mark.asyncio
    async def test_list_mode_opens_picker_and_mints_selection(self, mint_calls) -> None:
        """List mode asks for the otherwise ambiguous project and mints the selection."""
        app = _RoutingHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("m", "n")
            await pilot.pause()
            assert isinstance(app.screen, _ProjectPickerScreen)
            await pilot.press("enter")
            await pilot.pause()

        assert mint_calls == ["alpha"]

    @pytest.mark.asyncio
    async def test_inventory_picker_mints_selection(self, mint_calls) -> None:
        """Inventory mode carries the project picker result into the minting API."""
        app = _RoutingHost()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("i", "n")
            await pilot.pause()
            assert isinstance(app.screen, _ProjectPickerScreen)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, KeyInventoryScreen)

        assert mint_calls == ["alpha"]


class TestKeyLabel:
    """A key's display label prefers its comment, else type + fingerprint."""

    def test_uses_comment_when_present(self):
        """A commented key shows its comment."""
        assert _key_label(_row(comment="tk-main:foo")) == "tk-main:foo"

    def test_falls_back_to_type_and_fingerprint(self):
        """A blank comment yields the key type and a 16-char fingerprint prefix."""
        label = _key_label(_row(comment="", fingerprint="SHA256:0123456789abcdef0"))
        assert label == "ed25519 SHA256:012345678"


class TestInventoryLabel:
    """The catalog row carries metadata and the projects served."""

    def test_lists_served_projects(self):
        """Linked scopes appear; type and fingerprint are spelled out in full."""
        label = _inventory_label(_row(comment="k"), ["bar", "foo"])
        assert "ed25519  SHA256:abcdef" in label
        assert "projects: bar, foo" in label

    def test_unlinked_key_shows_dash(self):
        """A key with no projects renders an em dash."""
        assert "projects: —" in _inventory_label(_row(), [])


class TestApplyGuard:
    """Every vault mutation funnels through _apply, which must catch failures."""

    def test_success_reloads_without_toast(self):
        """A clean mutation repaints and raises no notification."""
        duck = SimpleNamespace(app=mock.Mock(), reload=mock.Mock())
        _BaseRoutingScreen._apply(duck, lambda: None, "Boom")
        duck.reload.assert_called_once()
        duck.app.notify.assert_not_called()

    def test_failure_toasts_and_skips_reload(self):
        """A raising mutation is caught, surfaced as an error, and does not repaint."""
        duck = SimpleNamespace(app=mock.Mock(), reload=mock.Mock())

        def boom():
            raise RuntimeError("vault locked")

        _BaseRoutingScreen._apply(duck, boom, "Unlink failed")
        duck.app.notify.assert_called_once()
        assert "Unlink failed" in duck.app.notify.call_args[0][0]
        assert duck.app.notify.call_args.kwargs["severity"] == "error"
        duck.reload.assert_not_called()


class TestHint:
    """The footer-style hint flips the mode label and colours its keys."""

    def test_m_names_the_target_mode(self):
        """``m`` advertises the mode it switches to, not the current one."""
        assert "m[/] list mode" in _hint(list_mode=False)
        assert "m[/] matrix mode" in _hint(list_mode=True)

    def test_keys_wear_the_footer_colour(self):
        """Every shortcut key is wrapped in the footer key-colour variable."""
        assert "[$footer-key-foreground]space[/]" in _hint(list_mode=False)
        assert "[$footer-key-foreground]r[/]" in _hint(list_mode=False)
