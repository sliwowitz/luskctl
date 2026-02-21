"""luskctl package.

Modules:
- luskctl.cli: CLI entry point package (luskctl)
- luskctl.tui: Text UI entry point package (luskctl-tui)
- luskctl.core: Configuration, projects, images, paths, version
- luskctl.containers: Task lifecycle, container runtime, Docker, Podman
- luskctl.security: Auth, SSH, git gate
- luskctl.ui: Terminal, clipboard, editor, shell launch
- luskctl.wizards: Interactive project creation
- luskctl.integrations: External API clients (Mistral)
- luskctl._util: Internal helpers (fs, templates, logging)
- luskctl.lib: Backward-compat shim (re-exports from new packages)
"""

__all__ = [
    "cli",
    "tui",
    "core",
    "containers",
    "security",
    "ui",
    "wizards",
    "integrations",
    "_util",
    "lib",  # backward-compat shim
]

# Version information - single source of truth using importlib.metadata
try:
    from importlib.metadata import version

    __version__ = version("luskctl")
except Exception:
    # Fallback for development mode when package is not installed
    try:
        import tomllib
        from pathlib import Path

        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
        if pyproject_path.exists():
            with open(pyproject_path, "rb") as f:
                pyproject_data = tomllib.load(f)
                __version__ = pyproject_data["tool"]["poetry"]["version"]
        else:
            __version__ = "unknown"
    except Exception:
        __version__ = "unknown"
