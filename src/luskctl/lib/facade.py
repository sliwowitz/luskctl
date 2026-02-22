"""Service facade for common cross-cutting operations.

Provides a single entry point for operations that both the CLI and TUI
frontends use, reducing the number of direct service-module imports
required by the presentation layer.

The facade re-exports key service functions and provides composite
helpers for multi-step workflows like project initialization.
"""

from .containers.docker import build_images, generate_dockerfiles
from .containers.environment import WEB_BACKENDS
from .security.auth import blablador_auth, claude_auth, codex_auth, mistral_auth
from .security.git_gate import sync_project_gate
from .security.ssh import init_project_ssh

__all__ = [
    # Docker / image management
    "generate_dockerfiles",
    "build_images",
    # Environment
    "WEB_BACKENDS",
    # Security setup
    "init_project_ssh",
    "sync_project_gate",
    # Auth providers
    "codex_auth",
    "claude_auth",
    "mistral_auth",
    "blablador_auth",
]
