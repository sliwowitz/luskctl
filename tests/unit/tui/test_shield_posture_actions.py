# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""The shield posture actions of ``TaskActionsMixin``: down, up, disengage, and the kill-switch guard.

Driven unbound on a ``SimpleNamespace`` app double, the way
``test_login_action`` drives ``_action_login`` — no Textual app boots.
"""

from __future__ import annotations

from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock

import pytest

from terok.tui import task_actions as task_actions_mod
from terok.tui.task_actions import TaskActionsMixin
from tests.testfs import MOCK_BASE

_POSTURE_ACTIONS = [
    pytest.param("_action_shield_down", "down", id="down"),
    pytest.param("_action_shield_up", "up", id="up"),
    pytest.param("_action_shield_disengaged", "down", id="disengaged"),
    pytest.param("action_shield_down_from_main", "down", id="down-from-main"),
    pytest.param("action_shield_up_from_main", "up", id="up-from-main"),
    pytest.param("action_shield_disengaged_from_main", "down", id="disengaged-from-main"),
]


def _app_stub(monkeypatch: pytest.MonkeyPatch, *, disabled: bool) -> SimpleNamespace:
    """App double whose config reports the kill-switch as *disabled*.

    ``_action_shield_toggle`` is recorded, not run; the guard and the
    disengage action are the real mixin methods bound onto the double so
    the actions reach them the way the app does.
    """
    cfg = SimpleNamespace(
        shield_disable_firewall_no_protection=disabled, shield_security_hint="see the docs"
    )
    monkeypatch.setattr(task_actions_mod, "get_config", lambda: cfg)
    stub = SimpleNamespace(notify=MagicMock(), _action_shield_toggle=MagicMock())
    for name in ("_notify_shield_disabled", "_action_shield_disengaged"):
        setattr(stub, name, MethodType(getattr(TaskActionsMixin, name), stub))
    return stub


@pytest.mark.parametrize(("action", "posture"), _POSTURE_ACTIONS)
def test_posture_action_toggles_when_firewall_enabled(
    monkeypatch: pytest.MonkeyPatch, action: str, posture: str
) -> None:
    """With the kill-switch off, each action hands its posture to ``_action_shield_toggle``."""
    stub = _app_stub(monkeypatch, disabled=False)

    getattr(TaskActionsMixin, action)(stub)

    stub._action_shield_toggle.assert_called_once()
    assert stub._action_shield_toggle.call_args.args[0] == posture
    stub.notify.assert_not_called()


@pytest.mark.parametrize(("action", "_posture"), _POSTURE_ACTIONS)
def test_posture_action_refuses_when_firewall_disabled(
    monkeypatch: pytest.MonkeyPatch, action: str, _posture: str
) -> None:
    """With the kill-switch set, each action notifies the operator and never toggles."""
    stub = _app_stub(monkeypatch, disabled=True)

    getattr(TaskActionsMixin, action)(stub)

    stub._action_shield_toggle.assert_not_called()
    stub.notify.assert_called_once()
    assert "disable_firewall_no_protection" in stub.notify.call_args.args[0]


def test_disengage_takes_the_shield_down_disengaged(monkeypatch: pytest.MonkeyPatch) -> None:
    """The disengage action's shield function calls ``ShieldManager.down(..., disengaged=True)``."""
    stub = _app_stub(monkeypatch, disabled=False)
    TaskActionsMixin._action_shield_disengaged(stub)
    shield_fn = stub._action_shield_toggle.call_args.args[1]
    manager = MagicMock()

    with (
        mock.patch.object(task_actions_mod, "ShieldManager", return_value=manager),
        mock.patch(
            "terok.lib.orchestration.task_runners.resolve_container_uuid", return_value="cafef00d"
        ),
    ):
        shield_fn("ctr", Path(MOCK_BASE) / "task")

    manager.down.assert_called_once_with("ctr", "cafef00d", disengaged=True)
