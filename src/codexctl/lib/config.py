from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import yaml  # pip install pyyaml

from .paths import config_root as _config_root_base, state_root as _state_root_base


# ---------- Prefix & roots ----------

def get_prefix() -> Path:
    """
    Minimal prefix helper used primarily for pip/venv installs.

    Order:
    - If CODEXCTL_PREFIX is set, use it.
    - Otherwise, use sys.prefix.

    Note: Do not use this for config/data discovery - see the dedicated
    helpers below which follow common Linux/XDG conventions.
    """
    env = os.environ.get("CODEXCTL_PREFIX")
    if env:
        return Path(env).expanduser().resolve()
    return Path(sys.prefix).resolve()


def config_root() -> Path:
    """
    System projects directory. Uses FHS/XDG via codexctl.lib.paths.

    Behavior:
    - If the base config directory contains a 'projects' subdirectory, use it.
    - Otherwise, treat the base config directory itself as the projects root.

    This makes development convenient when CODEXCTL_CONFIG_DIR points directly
    to a folder that already contains per-project subdirectories (like ./examples).
    """
    base = _config_root_base().resolve()
    proj_dir = base / "projects"
    return proj_dir if proj_dir.is_dir() else base


def global_config_search_paths() -> list[Path]:
    """Return the ordered list of paths that will be checked for global config.

    Behavior matches global_config_path():
    - If CODEXCTL_CONFIG_FILE is set, only that single path is considered.
    - Otherwise, check in order:
        1) ${XDG_CONFIG_HOME:-~/.config}/codexctl/config.yml
        2) sys.prefix/etc/codexctl/config.yml
        3) /etc/codexctl/config.yml
    """
    env_file = os.environ.get("CODEXCTL_CONFIG_FILE")
    if env_file:
        return [Path(env_file).expanduser().resolve()]

    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    user_cfg = (Path(xdg_home) if xdg_home else Path.home() / ".config") / "codexctl" / "config.yml"
    sp_cfg = Path(sys.prefix) / "etc" / "codexctl" / "config.yml"
    etc_cfg = Path("/etc/codexctl/config.yml")
    return [user_cfg, sp_cfg, etc_cfg]


def global_config_path() -> Path:
    """Global config file path (resolved based on search paths).

    Resolution order (first existing wins, except explicit override is returned even
    if missing to make intent visible to the user):
    - CODEXCTL_CONFIG_FILE env (returned as-is)
    - ${XDG_CONFIG_HOME:-~/.config}/codexctl/config.yml (user override)
    - sys.prefix/etc/codexctl/config.yml (pip wheels)
    - /etc/codexctl/config.yml (system default)
    If none exist, return the last path (/etc/codexctl/config.yml).
    """
    candidates = global_config_search_paths()
    # If CODEXCTL_CONFIG_FILE is set, candidates has a single element and we
    # want to return it even if it doesn't exist.
    if len(candidates) == 1:
        return candidates[0]

    for c in candidates:
        if c.is_file():
            return c.resolve()
    return candidates[-1]


# ---------- Global config (UI base port) ----------

def load_global_config() -> dict:
    cfg_path = global_config_path()
    if not cfg_path.is_file():
        return {}
    return yaml.safe_load(cfg_path.read_text()) or {}


def state_root() -> Path:
    """Writable state directory for tasks/cache/build.

    Precedence:
    - Environment variable CODEXCTL_STATE_DIR (handled first)
    - If set in global config (paths.state_root), use it.
    - Otherwise, use codexctl.lib.paths.state_root() (FHS/XDG handling).
    """
    # Environment override should always win
    env = os.environ.get("CODEXCTL_STATE_DIR")
    if env:
        return Path(env).expanduser().resolve()

    try:
        cfg = load_global_config()
        cfg_path = (cfg.get("paths", {}) or {}).get("state_root")
        if cfg_path:
            return Path(cfg_path).expanduser().resolve()
    except Exception:
        # Be resilient to any config read error
        pass
    return _state_root_base().resolve()


def user_projects_root() -> Path:
    # Global config override
    try:
        cfg = load_global_config()
        up = (cfg.get("paths", {}) or {}).get("user_projects_root")
        if up:
            return Path(up).expanduser().resolve()
    except Exception:
        # Fall back to state_root() if global config is missing or invalid.
        pass

    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "codexctl" / "projects"
    return Path.home() / ".config" / "codexctl" / "projects"


def build_root() -> Path:
    """
    Directory for build artifacts (generated Dockerfiles, etc.).

    Resolution order:
    - Global config: paths.build_root
    - Otherwise: state_root()/build
    """
    # Global config preferred
    try:
        cfg = load_global_config()
        paths_cfg = cfg.get("paths", {}) or {}
        br = paths_cfg.get("build_root")
        if br:
            return Path(br).expanduser().resolve()
    except Exception:
        pass

    sr = state_root()
    return (sr / "build").resolve()


def get_ui_base_port() -> int:
    cfg = load_global_config()
    ui_cfg = cfg.get("ui", {}) or {}
    return int(ui_cfg.get("base_port", 7860))


def get_envs_base_dir() -> Path:
    """Return the base directory for shared env mounts (codex/ssh).

    Global config (codexctl-config.yml):
      envs:
        base_dir: /var/lib/codexctl/envs

    Default: /var/lib/codexctl/envs
    """
    cfg = load_global_config()
    envs_cfg = cfg.get("envs", {}) or {}
    base = envs_cfg.get("base_dir", "/var/lib/codexctl/envs")
    return Path(str(base)).expanduser().resolve()


def get_global_human_name() -> Optional[str]:
    """Return git.human_name from global config, or None if not set."""
    cfg = load_global_config()
    git_cfg = cfg.get("git", {}) or {}
    return git_cfg.get("human_name")


def get_global_human_email() -> Optional[str]:
    """Return git.human_email from global config, or None if not set."""
    cfg = load_global_config()
    git_cfg = cfg.get("git", {}) or {}
    return git_cfg.get("human_email")
