# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Tests for the [`ShieldSetsScreen`][terok.tui.shield_sets_screen.ShieldSetsScreen] egress-set picker.

Pins the dismissal contract the Project Details caller relies on:
``DEFAULT_SELECTION`` for the master-"All" (generous default) state, an
explicit tuple otherwise (empty = curated content disabled), ``None`` on
cancel — plus the master/item cascade shared with the agents picker.
"""

from __future__ import annotations

import pytest
from textual.app import App
from textual.widgets import Checkbox

from terok.lib.api import EGRESS_SETS
from terok.tui.shield_sets_screen import DEFAULT_SELECTION, ShieldSetsScreen

_SENTINEL_PENDING = object()
_SLUGS = tuple(EGRESS_SETS)


class _Host(App):
    """Minimal test host that pushes a screen and captures its dismissal value."""

    def __init__(self, screen: ShieldSetsScreen) -> None:
        super().__init__()
        self._screen = screen
        self.result: object = _SENTINEL_PENDING

    def on_mount(self) -> None:
        self.push_screen(self._screen, self._capture)

    def _capture(self, result: object) -> None:
        self.result = result


def _master(screen: ShieldSetsScreen) -> Checkbox:
    return screen.query_one("#shield-sets-all", Checkbox)


def _item(screen: ShieldSetsScreen, slug: str) -> Checkbox:
    return screen.query_one(f"#shield-sets-item-{slug}", Checkbox)


@pytest.mark.asyncio
async def test_unset_initial_is_master_on() -> None:
    """``initial=None`` (generous default) → master checked, every item checked."""
    app = _Host(ShieldSetsScreen(initial=None))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ShieldSetsScreen)
        assert _master(screen).value is True
        for slug in _SLUGS:
            assert _item(screen, slug).value is True


@pytest.mark.asyncio
async def test_explicit_initial_seeds_named_items_only() -> None:
    """An explicit selection seeds exactly its items, master off."""
    pick = _SLUGS[0]
    app = _Host(ShieldSetsScreen(initial=(pick,)))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert _master(screen).value is False
        assert _item(screen, pick).value is True
        for other in _SLUGS[1:]:
            assert _item(screen, other).value is False


@pytest.mark.asyncio
async def test_unchecking_item_flips_master_off() -> None:
    """Removing one set with master on means the snapshot diverges from the default."""
    app = _Host(ShieldSetsScreen(initial=None))
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        _item(screen, _SLUGS[0]).value = False
        await pilot.pause()
        assert _master(screen).value is False


@pytest.mark.asyncio
async def test_save_with_master_emits_default_sentinel() -> None:
    """Save with master on returns ``DEFAULT_SELECTION`` — written as null (inherit)."""
    app = _Host(ShieldSetsScreen(initial=None))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#shield-sets-save")
        await pilot.pause()
    assert app.result == DEFAULT_SELECTION


@pytest.mark.asyncio
async def test_save_with_subset_emits_tuple() -> None:
    """Master off + named items → an explicit frozen tuple."""
    app = _Host(ShieldSetsScreen(initial=(_SLUGS[0], _SLUGS[1])))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#shield-sets-save")
        await pilot.pause()
    assert app.result == (_SLUGS[0], _SLUGS[1])


@pytest.mark.asyncio
async def test_save_with_nothing_selected_emits_empty_tuple() -> None:
    """Unlike agents, an empty selection is valid: curated content deliberately off."""
    app = _Host(ShieldSetsScreen(initial=()))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#shield-sets-save")
        await pilot.pause()
    assert app.result == ()


@pytest.mark.asyncio
async def test_cancel_dismisses_with_none() -> None:
    """Cancel returns ``None`` — caller treats as no change."""
    app = _Host(ShieldSetsScreen(initial=None))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#shield-sets-cancel")
        await pilot.pause()
    assert app.result is None
