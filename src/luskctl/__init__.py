"""luskctl package.

Modules:
- luskctl.cli: CLI entry point package (luskctl)
- luskctl.tui: Text UI entry point package (luskctl-tui)
- luskctl.tui.widgets: TUI widgets
- luskctl.lib: Core library package (auth, config, docker, git_gate, projects, ssh, tasks)
- luskctl.lib.paths: Base path helpers
"""

__all__ = [
    "cli",
    "lib",
    "tui",
]

# Version information
try:
    # Try to read from pyproject.toml during development
    import tomllib
    from pathlib import Path

    pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
    if pyproject_path.exists():
        with open(pyproject_path, "rb") as f:
            pyproject_data = tomllib.load(f)
            __version__ = pyproject_data["tool"]["poetry"]["version"]
    else:
        __version__ = "0.3.1"  # Fallback to current version
except Exception:
    __version__ = "0.3.1"  # Fallback to current version
