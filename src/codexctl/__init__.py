"""codexctl package.

Modules:
- codexctl.cli: CLI entry point (codexctl)
- codexctl.tui: Text UI entry point (codexctl-tui / codextui)
- codexctl.lib: Compatibility shim (legacy core library)
- codexctl.config: Config + path helpers
- codexctl.projects: Project model + loading
- codexctl.docker: Dockerfile generation + image build
- codexctl.tasks: Task management + podman run helpers
- codexctl.ssh: SSH init helpers
- codexctl.git_cache: Git mirror cache helpers
- codexctl.auth: Codex auth helper
- codexctl.widgets: TUI widgets
"""

__all__ = [
    "auth",
    "cli",
    "config",
    "docker",
    "git_cache",
    "lib",
    "projects",
    "ssh",
    "tasks",
    "tui",
    "widgets",
]
