# SPDX-FileCopyrightText: 2025 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Unit-test fixtures.

Auto-mocks sandbox and shield helpers in task runners so existing tests
do not require a real OCI hook, nftables, podman, or root privileges.
"""

from collections.abc import Iterator
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _mock_shield_helpers() -> Iterator[None]:
    """Replace Sandbox.run and shield down with no-ops."""
    with (
        patch(
            "terok.lib.orchestration.task_runners._sandbox",
        ),
        patch(
            "terok.lib.orchestration.task_runners._shield_down_impl",
        ),
    ):
        yield
