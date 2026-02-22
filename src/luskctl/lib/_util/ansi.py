"""Pure ANSI color utilities for service-layer modules.

This module provides the low-level color functions that service-layer code
may use without depending on the presentation-layer ``ui_utils.terminal``
module.  The higher-level ``ui_utils.terminal`` re-exports these and adds
extra helpers (``yes_no``, ``violet``, ``gray``).
"""

import os
import sys


def supports_color() -> bool:
    """Check if stdout supports color output.

    Follows the NO_COLOR standard (https://no-color.org/).
    """
    if "NO_COLOR" in os.environ:
        return False
    return sys.stdout.isatty()


def color(text: str, code: str, enabled: bool) -> str:
    """Wrap *text* in ANSI escape codes when *enabled* is True.

    Args:
        text: The string to colorize.
        code: ANSI SGR parameter (e.g. ``"31"`` for red).
        enabled: When False the original *text* is returned unchanged.
    """
    if not enabled:
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def yellow(text: str, enabled: bool) -> str:
    """Return *text* in yellow (ANSI 33) when *enabled*."""
    return color(text, "33", enabled)


def blue(text: str, enabled: bool) -> str:
    """Return *text* in blue (ANSI 34) when *enabled*."""
    return color(text, "34", enabled)


def green(text: str, enabled: bool) -> str:
    """Return *text* in green (ANSI 32) when *enabled*."""
    return color(text, "32", enabled)


def red(text: str, enabled: bool) -> str:
    """Return *text* in red (ANSI 31) when *enabled*."""
    return color(text, "31", enabled)
