import os
import sys
from pathlib import Path

import yaml  # pip install pyyaml

from .paths import config_root as _config_root_base
from .paths import state_root as _state_root_base

# ---------- Prefix & roots ----------


def get_prefix() -> Path:
    """
    Minimal prefix helper used primarily for pip/venv installs.

    Order:
    - If LUSKCTL_PREFIX is set, use it.
    - Otherwise, use sys.prefix.

    Note: Do not use this for config/data discovery - see the dedicated
    helpers below which follow common Linux/XDG conventions.
    """
    env = os.environ.get("LUSKCTL_PREFIX")
    if env:
        return Path(env).expanduser().resolve()
    return Path(sys.prefix).resolve()


def config_root() -> Path:
    """
    System projects directory. Uses FHS/XDG via luskctl.lib.paths.

    Behavior:
    - If the base config directory contains a 'projects' subdirectory, use it.
    - Otherwise, treat the base config directory itself as the projects root.

    This makes development convenient when LUSKCTL_CONFIG_DIR points directly
    to a folder that already contains per-project subdirectories (like ./examples).
    """
    base = _config_root_base().resolve()
    proj_dir = base / "projects"
    return proj_dir if proj_dir.is_dir() else base


def global_config_search_paths() -> list[Path]:
    """Return the ordered list of paths that will be checked for global config.

    Behavior matches global_config_path():
    - If LUSKCTL_CONFIG_FILE is set, only that single path is considered.
    - Otherwise, check in order:
        1) ${XDG_CONFIG_HOME:-~/.config}/luskctl/config.yml
        2) sys.prefix/etc/luskctl/config.yml
        3) /etc/luskctl/config.yml
    """
    env_file = os.environ.get("LUSKCTL_CONFIG_FILE")
    if env_file:
        return [Path(env_file).expanduser().resolve()]

    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    user_cfg = (Path(xdg_home) if xdg_home else Path.home() / ".config") / "luskctl" / "config.yml"
    sp_cfg = Path(sys.prefix) / "etc" / "luskctl" / "config.yml"
    etc_cfg = Path("/etc/luskctl/config.yml")
    return [user_cfg, sp_cfg, etc_cfg]


def global_config_path() -> Path:
    """Global config file path (resolved based on search paths).

    Resolution order (first existing wins, except explicit override is returned even
    if missing to make intent visible to the user):
    - LUSKCTL_CONFIG_FILE env (returned as-is)
    - ${XDG_CONFIG_HOME:-~/.config}/luskctl/config.yml (user override)
    - sys.prefix/etc/luskctl/config.yml (pip wheels)
    - /etc/luskctl/config.yml (system default)
    If none exist, return the last path (/etc/luskctl/config.yml).
    """
    candidates = global_config_search_paths()
    # If LUSKCTL_CONFIG_FILE is set, candidates has a single element and we
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
    - Environment variable LUSKCTL_STATE_DIR (handled first)
    - If set in global config (paths.state_root), use it.
    - Otherwise, use luskctl.lib.paths.state_root() (FHS/XDG handling).
    """
    # Environment override should always win
    env = os.environ.get("LUSKCTL_STATE_DIR")
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
        return Path(xdg) / "luskctl" / "projects"
    return Path.home() / ".config" / "luskctl" / "projects"


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

    Global config (luskctl-config.yml):
      envs:
        base_dir: ~/.local/share/luskctl/envs  # or /var/lib/luskctl/envs for root

    Default: ~/.local/share/luskctl/envs (or /var/lib/luskctl/envs if root)
    """
    cfg = load_global_config()
    envs_cfg = cfg.get("envs", {}) or {}

    # If explicitly configured, use that
    if "base_dir" in envs_cfg:
        base = envs_cfg["base_dir"]
        return Path(str(base)).expanduser().resolve()

    # Otherwise, use the same pattern as state_root()
    # For non-root users: ~/.local/share/luskctl/envs
    # For root users: /var/lib/luskctl/envs
    return (_state_root_base() / "envs").resolve()


def get_global_human_name() -> str | None:
    """Return git.human_name from global config, or None if not set."""
    cfg = load_global_config()
    git_cfg = cfg.get("git", {}) or {}
    return git_cfg.get("human_name")


def get_global_human_email() -> str | None:
    """Return git.human_email from global config, or None if not set."""
    cfg = load_global_config()
    git_cfg = cfg.get("git", {}) or {}
    return git_cfg.get("human_email")


def get_global_default_agent() -> str | None:
    """Return default_agent from global config, or None if not set."""
    cfg = load_global_config()
    return cfg.get("default_agent")
