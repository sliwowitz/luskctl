"""Utility functions for logging."""


def _log_debug(message: str) -> None:
    """Append a simple debug line to the luskctl library log.

    This is intentionally very small and best-effort so it never interferes
    with normal CLI or TUI behavior. It can be used to compare behavior
    between different frontends (e.g. CLI vs TUI) when calling the shared
    helpers in this module.
    """
    # Implementation can be added here
    # For now, this breaks the circular dependency
    pass
