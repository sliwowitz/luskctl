import os
import sys
from collections.abc import Callable
from importlib import resources as _pkg_resources
from pathlib import Path
from typing import Any

import yaml  # pip install pyyaml

from .paths import config_root as _config_root_base, state_root as _state_root_base

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


# ---------- Global config (cached) ----------


def load_global_config() -> dict[str, Any]:
    cfg_path = global_config_path()
    if not cfg_path.is_file():
        return {}
    return yaml.safe_load(cfg_path.read_text()) or {}


def get_global_section(key: str) -> dict[str, Any]:
    """Return a top-level section from the global config, defaulting to ``{}``.

    If the value under *key* is not a dict (e.g. the user wrote ``git: "oops"``),
    returns ``{}`` to avoid ``AttributeError`` in callers that expect ``.get()``.
    """
    cfg = load_global_config()
    value = cfg.get(key, {})
    if not isinstance(value, dict):
        return {}
    return value or {}


# ---------- Path resolution ----------


def _resolve_path(
    env_var: str | None,
    config_key: tuple[str, str] | None,
    default: Callable[[], Path],
) -> Path:
    """Resolve a path: env var → global config → computed default.

    This replaces the repeated try/except + load_global_config() pattern
    that was duplicated across ``state_root``, ``build_root``, etc.
    """
    if env_var:
        env = os.environ.get(env_var)
        if env:
            return Path(env).expanduser().resolve()

    if config_key:
        try:
            section = get_global_section(config_key[0])
            val = section.get(config_key[1])
            if val:
                return Path(val).expanduser().resolve()
        except (OSError, KeyError, TypeError, yaml.YAMLError):
            pass

    return default().resolve()


def state_root() -> Path:
    """Writable state directory for tasks/cache/build.

    Precedence:
    - Environment variable LUSKCTL_STATE_DIR (handled first)
    - If set in global config (paths.state_root), use it.
    - Otherwise, use luskctl.lib.paths.state_root() (FHS/XDG handling).
    """
    return _resolve_path("LUSKCTL_STATE_DIR", ("paths", "state_root"), _state_root_base)


def user_projects_root() -> Path:
    """User projects directory.

    Precedence:
    - Global config: paths.user_projects_root
    - XDG_CONFIG_HOME/luskctl/projects
    - ~/.config/luskctl/projects
    """

    def _default() -> Path:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            return Path(xdg) / "luskctl" / "projects"
        return Path.home() / ".config" / "luskctl" / "projects"

    return _resolve_path(None, ("paths", "user_projects_root"), _default)


def global_presets_dir() -> Path:
    """Global presets directory (shared across all projects).

    Precedence:
    - Global config: paths.global_presets_dir
    - XDG_CONFIG_HOME/luskctl/presets
    - ~/.config/luskctl/presets
    """

    def _default() -> Path:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            return Path(xdg) / "luskctl" / "presets"
        return Path.home() / ".config" / "luskctl" / "presets"

    return _resolve_path(None, ("paths", "global_presets_dir"), _default)


def bundled_presets_dir() -> Path:
    """Presets shipped with the luskctl package.

    These serve as ready-to-use defaults that users can reference directly
    (``--preset solo``) or copy to their global presets dir to customize.
    Lowest priority in the search order: project > global > bundled.
    """
    return Path(str(_pkg_resources.files("luskctl") / "resources" / "presets"))


def build_root() -> Path:
    """
    Directory for build artifacts (generated Dockerfiles, etc.).

    Resolution order:
    - Global config: paths.build_root
    - Otherwise: state_root()/build
    """
    return _resolve_path(None, ("paths", "build_root"), lambda: state_root() / "build")


def get_ui_base_port() -> int:
    """Return the base port for the web UI (default 7860)."""
    return int(get_global_section("ui").get("base_port", 7860))


def get_envs_base_dir() -> Path:
    """Return the base directory for shared env mounts (codex/ssh).

    Global config (luskctl-config.yml):
      envs:
        base_dir: ~/.local/share/luskctl/envs  # or /var/lib/luskctl/envs for root

    Default: ~/.local/share/luskctl/envs (or /var/lib/luskctl/envs if root)
    """
    return _resolve_path(None, ("envs", "base_dir"), lambda: _state_root_base() / "envs")


def get_global_human_name() -> str | None:
    """Return git.human_name from global config, or None if not set."""
    return get_global_section("git").get("human_name")


def get_global_human_email() -> str | None:
    """Return git.human_email from global config, or None if not set."""
    return get_global_section("git").get("human_email")


def get_global_default_agent() -> str | None:
    """Return default_agent from global config, or None if not set."""
    cfg = load_global_config()
    return cfg.get("default_agent")


def get_tui_default_tmux() -> bool:
    """Return whether to default to tmux mode for TUI, or False if not set."""
    return bool(get_global_section("tui").get("default_tmux", False))


def get_global_agent_config() -> dict[str, Any]:
    """Return the ``agent:`` section from the global config, or ``{}``."""
    return get_global_section("agent")
