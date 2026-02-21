"""Backward-compat shim — re-exports all modules under their old names.

Allows ``from luskctl.lib import config`` etc. to keep working for any
downstream code that hasn't migrated to the new package layout yet.
"""

from luskctl._util import fs, logging_utils, podman, template_utils
from luskctl.containers import agents, autopilot, docker, project_state, tasks
from luskctl.containers import environment as task_env
from luskctl.containers import ports as task_ports
from luskctl.containers import runtime as container_utils
from luskctl.core import config, images, paths, projects, version
from luskctl.integrations import mistral_model_sync
from luskctl.security import auth, git_gate, ssh
from luskctl.tui import clipboard, shell_launch
from luskctl.ui import editor, terminal
from luskctl.wizards import new_project as wizard

__all__ = [
    "config",
    "paths",
    "projects",
    "images",
    "version",
    "tasks",
    "container_utils",
    "task_env",
    "task_ports",
    "agents",
    "autopilot",
    "docker",
    "podman",
    "project_state",
    "auth",
    "ssh",
    "git_gate",
    "terminal",
    "clipboard",
    "editor",
    "shell_launch",
    "wizard",
    "mistral_model_sync",
    "fs",
    "template_utils",
    "logging_utils",
]
