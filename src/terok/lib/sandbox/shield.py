# SPDX-FileCopyrightText: 2025 Jiri Vyskocil
# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0
"""Re-export: shield egress firewall adapter from ``terok_sandbox.shield``."""

from terok_sandbox.shield import *  # noqa: F401,F403
from terok_sandbox.shield import _BYPASS_WARNING  # noqa: F401 — used by tests
