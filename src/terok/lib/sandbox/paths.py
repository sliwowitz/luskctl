# SPDX-FileCopyrightText: 2025 Jiri Vyskocil
# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Platform-aware path resolution for sandbox directories.

Vendored from ``core.paths`` — zero internal dependencies.  Provides
the same XDG / FHS resolution logic so that ``terok-sandbox`` works
identically whether embedded in terok or used standalone.
"""

import getpass
import os
from pathlib import Path

try:
    from platformdirs import (
        user_config_dir as _user_config_dir,
        user_data_dir as _user_data_dir,
    )
except ImportError:  # optional dependency
    _user_config_dir = _user_data_dir = None  # type: ignore[assignment]


APP_NAME = "terok"


def _is_root() -> bool:
    """Return True if the current process is running as root."""
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except AttributeError:
        return getpass.getuser() == "root"


def config_root() -> Path:
    """Base directory for configuration.

    Priority: ``TEROK_CONFIG_DIR`` → ``/etc/terok`` (root) → ``~/.config/terok``.
    """
    env = os.getenv("TEROK_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    if _is_root():
        return Path("/etc") / APP_NAME
    if _user_config_dir is not None:
        return Path(_user_config_dir(APP_NAME))
    return Path.home() / ".config" / APP_NAME


def state_root() -> Path:
    """Writable state root (tasks, tokens, caches).

    Priority: ``TEROK_STATE_DIR`` → ``/var/lib/terok`` (root) → XDG data dir.
    """
    env = os.getenv("TEROK_STATE_DIR")
    if env:
        return Path(env).expanduser()
    if _is_root():
        return Path("/var/lib") / APP_NAME
    if _user_data_dir is not None:
        return Path(_user_data_dir(APP_NAME))
    xdg = os.getenv("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def runtime_root() -> Path:
    """Transient runtime directory (PID files, sockets).

    Priority: ``TEROK_RUNTIME_DIR`` → ``/run/terok`` (root) → ``~/.cache/terok``.
    """
    env = os.getenv("TEROK_RUNTIME_DIR")
    if env:
        return Path(env).expanduser()
    if _is_root():
        return Path("/run") / APP_NAME
    return Path.home() / ".cache" / APP_NAME
