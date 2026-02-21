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
    if not enabled:
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def yellow(text: str, enabled: bool) -> str:
    return color(text, "33", enabled)


def blue(text: str, enabled: bool) -> str:
    return color(text, "34", enabled)


def green(text: str, enabled: bool) -> str:
    return color(text, "32", enabled)


def red(text: str, enabled: bool) -> str:
    return color(text, "31", enabled)


def yes_no(value: bool, enabled: bool) -> str:
    return color("yes" if value else "no", "32" if value else "31", enabled)


def violet(text: str, enabled: bool) -> str:
    return color(text, "35", enabled)


def gray(text: str, enabled: bool) -> str:
    return color(text, "90", enabled)
