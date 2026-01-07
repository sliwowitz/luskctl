from __future__ import annotations

import os
from pathlib import Path


def _ensure_dev_ownership(path: Path) -> None:
    """Best-effort chown to dev (uid/gid 1000) for shared mounts."""
    uid = 1000
    gid = 1000
    chown = getattr(os, "lchown", os.chown)
    try:
        chown(path, uid, gid)
    except Exception:
        return
    if not path.is_dir():
        return
    try:
        for root, dirs, files in os.walk(path):
            for name in dirs + files:
                try:
                    chown(Path(root) / name, uid, gid)
                except Exception:
                    continue
    except Exception:
        pass
