"""codexctl package.

Modules:
- codexctl.cli: CLI entry point package (codexctl)
- codexctl.tui: Text UI entry point package (codexctl-tui / codextui)
- codexctl.tui.widgets: TUI widgets
- codexctl.lib: Core library package (auth, config, docker, git_cache, projects, ssh, tasks)
- codexctl.lib.paths: Base path helpers
"""

__all__ = [
    "cli",
    "lib",
    "tui",
]
