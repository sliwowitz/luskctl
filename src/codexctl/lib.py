#!/usr/bin/env python3
# Compatibility shim for legacy imports from codexctl.lib.

from __future__ import annotations

from .auth import codex_auth
from .config import (
    build_root,
    config_root,
    get_envs_base_dir,
    get_prefix,
    get_ui_base_port,
    global_config_path,
    global_config_search_paths,
    load_global_config,
    state_root,
    user_projects_root,
)
from .docker import build_images, generate_dockerfiles
from .git_cache import init_project_cache
from .projects import Project, get_project_state, list_projects, load_project
from .ssh import init_project_ssh
from .tasks import (
    get_tasks,
    task_delete,
    task_list,
    task_new,
    task_run_cli,
    task_run_ui,
)

__all__ = [
    "Project",
    "build_images",
    "build_root",
    "codex_auth",
    "config_root",
    "generate_dockerfiles",
    "get_envs_base_dir",
    "get_prefix",
    "get_project_state",
    "get_tasks",
    "get_ui_base_port",
    "global_config_path",
    "global_config_search_paths",
    "init_project_cache",
    "init_project_ssh",
    "list_projects",
    "load_global_config",
    "load_project",
    "state_root",
    "task_delete",
    "task_list",
    "task_new",
    "task_run_cli",
    "task_run_ui",
    "user_projects_root",
]
