"""Utility to open files in the user's preferred editor."""

import os
import shutil
import subprocess
from pathlib import Path


def open_in_editor(file_path: Path) -> bool:
    """Open *file_path* in the user's preferred editor (blocking).

    Editor resolution order:
      1. ``$EDITOR`` environment variable
      2. ``nano``
      3. ``vi``

    Returns ``True`` if the editor was launched successfully, ``False`` if no
    usable editor was found (a message is printed to stderr in that case).
    """
    editor = _resolve_editor()
    if editor is None:
        print(
            "No editor found. Set the EDITOR environment variable or install nano/vi.",
        )
        return False

    try:
        subprocess.run([editor, str(file_path)], check=True)  # noqa: S603
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


def _resolve_editor() -> str | None:
    """Return the first available editor command, or *None*."""
    env_editor = os.environ.get("EDITOR", "").strip()
    if env_editor and shutil.which(env_editor):
        return env_editor

    for fallback in ("nano", "vi"):
        if shutil.which(fallback):
            return fallback

    return None
