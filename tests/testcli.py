# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for invoking the CLI entrypoint in tests."""

from __future__ import annotations

import sys
from unittest.mock import patch

from terok.cli.main import main


def run_cli(*argv: str, prog: str = "terok") -> None:
    """Run the CLI entrypoint with a temporary ``sys.argv``."""
    with patch.object(sys, "argv", [prog, *argv]):
        main()
