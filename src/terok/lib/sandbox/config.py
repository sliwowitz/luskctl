# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Sandbox configuration — plain dataclass for standalone and embedded use.

:class:`SandboxConfig` captures directory paths and settings that sandbox
modules need.  In standalone ``terok-sandbox`` use, it is resolved from
environment variables and XDG defaults.  When embedded in terok, the
orchestration layer constructs it from :func:`core.config` values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .paths import (
    config_root as _config_root,
    runtime_root as _runtime_root,
    state_root as _state_root,
)


@dataclass(frozen=True)
class SandboxConfig:
    """Immutable configuration for the sandbox layer.

    All paths default to the XDG/FHS-resolved values from ``core.paths``.
    Override individual fields when constructing from terok's global config
    or when using terok-sandbox standalone.
    """

    state_dir: Path = field(default_factory=_state_root)
    """Writable state root (tokens, gate repos, task data)."""

    runtime_dir: Path = field(default_factory=_runtime_root)
    """Transient runtime directory (PID files, sockets)."""

    config_dir: Path = field(default_factory=_config_root)
    """Configuration root (shield profiles)."""

    envs_dir: Path | None = None
    """Base directory for per-project environment data (SSH dirs, etc.).

    When ``None``, individual modules fall back to ``state_dir / "envs"``.
    """

    gate_port: int = 9418
    """HTTP port for the gate server."""

    shield_profiles: tuple[str, ...] = ("dev-standard",)
    """Shield egress firewall profile names."""

    shield_audit: bool = True
    """Whether shield audit logging is enabled."""

    shield_bypass: bool = False
    """DANGEROUS: when True, the egress firewall is completely disabled."""

    @property
    def effective_envs_dir(self) -> Path:
        """Return *envs_dir* or the default ``state_dir / "envs"``."""
        return self.envs_dir or self.state_dir / "envs"

    @property
    def gate_base_path(self) -> Path:
        """Return the gate server's repo base path."""
        return self.state_dir / "gate"

    @property
    def token_file_path(self) -> Path:
        """Return the path to the gate token file."""
        return self.state_dir / "gate" / "tokens.json"

    @property
    def pid_file_path(self) -> Path:
        """Return the PID file path for the managed gate daemon."""
        return self.runtime_dir / "gate-server.pid"

    @property
    def shield_profiles_dir(self) -> Path:
        """Return the directory for terok-managed shield profiles."""
        return self.config_dir / "shield" / "profiles"
