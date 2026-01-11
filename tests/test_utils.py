import unittest.mock
from pathlib import Path


def mock_git_config():
    """Return a mock for _get_global_git_config that returns None (no global git config)."""
    return unittest.mock.patch("luskctl.lib.projects._get_global_git_config", return_value=None)


def write_project(root: Path, project_id: str, yaml_text: str) -> Path:
    proj_dir = root / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "project.yml").write_text(yaml_text, encoding="utf-8")
    return proj_dir


def parse_meta_value(meta_text: str, key: str) -> str | None:
    for line in meta_text.splitlines():
        if line.startswith(f"{key}:"):
            value = line.split(":", 1)[1].strip()
            return value.strip("'\"")
    return None
