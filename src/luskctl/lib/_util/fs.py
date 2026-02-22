import os
from pathlib import Path


def ensure_dir(path: Path) -> None:
    """Create a directory (and parents) if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)


def ensure_dir_writable(path: Path, label: str) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise SystemExit(f"{label} directory is not writable: {path} ({e})")
    if not path.is_dir():
        raise SystemExit(f"{label} path is not a directory: {path}")
    if not os.access(path, os.W_OK | os.X_OK):
        uid = os.getuid()
        gid = os.getgid()
        raise SystemExit(
            f"{label} directory is not writable: {path}\n"
            f"Fix permissions for the user running luskctl (uid={uid}, gid={gid}). "
            f"Example: sudo chown -R {uid}:{gid} {path}"
        )
