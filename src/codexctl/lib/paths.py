import getpass
import os
from pathlib import Path

try:
    from platformdirs import (
        user_config_dir as _user_config_dir,
    )
    from platformdirs import (
        user_data_dir as _user_data_dir,
    )
except ImportError:  # optional dependency
    _user_config_dir = _user_data_dir = None  # type: ignore[assignment]


APP_NAME = "codexctl"


def _is_root() -> bool:
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except AttributeError:
        return getpass.getuser() == "root"


def config_root() -> Path:
    """
    Base directory for configuration (project.yml, projects/, etc.).

    Priority:
      1. CODEXCTL_CONFIG_DIR
      2. if root   → /etc/codexctl
         else      → ~/.config/codexctl
    """
    env = os.getenv("CODEXCTL_CONFIG_DIR")
    if env:
        return Path(env).expanduser()

    if _is_root():
        return Path("/etc") / APP_NAME

    if _user_config_dir is not None:
        return Path(_user_config_dir(APP_NAME))
    return Path.home() / ".config" / APP_NAME


def state_root() -> Path:
    """
    Writable state (tasks, pods, caches).

    Priority:
      1. CODEXCTL_STATE_DIR
      2. if root   → /var/lib/codexctl
         else      → ${XDG_DATA_HOME:-~/.local/share}/codexctl
    """
    env = os.getenv("CODEXCTL_STATE_DIR")
    if env:
        return Path(env).expanduser()

    if _is_root():
        return Path("/var/lib") / APP_NAME

    if _user_data_dir is not None:
        return Path(_user_data_dir(APP_NAME))

    # Fallback without platformdirs: honor XDG_DATA_HOME if set
    xdg = os.getenv("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def runtime_root() -> Path:
    """
    Transient runtime bits.

    Priority:
      1. CODEXCTL_RUNTIME_DIR
      2. if root   → /run/codexctl
         else      → ~/.cache/codexctl
    """
    env = os.getenv("CODEXCTL_RUNTIME_DIR")
    if env:
        return Path(env).expanduser()

    if _is_root():
        return Path("/run") / APP_NAME

    return Path.home() / ".cache" / APP_NAME
