from __future__ import annotations

from pathlib import Path
from typing import Optional


def write_project(root: Path, project_id: str, yaml_text: str) -> Path:
    proj_dir = root / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "project.yml").write_text(yaml_text, encoding="utf-8")
    return proj_dir


def parse_meta_value(meta_text: str, key: str) -> Optional[str]:
    for line in meta_text.splitlines():
        if line.startswith(f"{key}:"):
            value = line.split(":", 1)[1].strip()
            return value.strip("'\"")
    return None
