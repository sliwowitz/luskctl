# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""``TerokTUI._on_panic_stop_confirmed`` when the operator keeps the containers running.

The notification names why the containers are still exposed: the shield
kill-switch, or shields that failed during the lockdown.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from terok.tui.app import TerokTUI


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("panic_result", "expected"),
    [
        pytest.param(
            SimpleNamespace(shield_disabled=True, shield_errors=[]),
            "shields DISABLED",
            id="disabled",
        ),
        pytest.param(
            SimpleNamespace(shield_disabled=False, shield_errors=["ctr: nft missing"]),
            "some shields failed",
            id="errors",
        ),
    ],
)
async def test_declined_stop_names_the_exposure(
    panic_result: SimpleNamespace, expected: str
) -> None:
    """Declining the stop after a panic notifies with the reason the shields are not protecting."""
    stub = SimpleNamespace(notify=MagicMock(), _last_panic_result=panic_result)

    await TerokTUI._on_panic_stop_confirmed(stub, False)

    stub.notify.assert_called_once()
    assert expected in stub.notify.call_args.args[0]
