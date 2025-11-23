#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.widgets import ListView, ListItem, Static, Button
from textual.containers import Horizontal
from textual.message import Message

from .lib import Project as CodexProject


@dataclass
class TaskMeta:
    task_id: str
    status: str
    mode: Optional[str]
    workspace: str
    ui_port: Optional[int]


class ProjectList(ListView):
    """Left-hand project list widget."""

    class ProjectSelected(Message):
        def __init__(self, project_id: str) -> None:
            super().__init__()
            self.project_id = project_id

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.projects: List[CodexProject] = []

    def set_projects(self, projects: List[CodexProject]) -> None:
        """Populate the list with projects."""
        self.projects = projects
        self.clear()
        for proj in projects:
            label = f"{proj.id} [{proj.security_class}]"
            # Disable Rich markup to avoid surprises
            self.append(ListItem(Static(label, markup=False)))

    def select_project(self, project_id: str) -> None:
        """Select a project by id."""
        for idx, proj in enumerate(self.projects):
            if proj.id == project_id:
                self.index = idx
                break

    def on_list_view_selected(self, event: ListView.Selected) -> None:  # type: ignore[override]
        """When user selects a row, send a semantic ProjectSelected message."""
        idx = self.index
        if 0 <= idx < len(self.projects):
            proj_id = self.projects[idx].id
            self.post_message(self.ProjectSelected(proj_id))


class ProjectActions(Static):
    """Single-row action bar for project + task actions."""
    def compose(self) -> ComposeResult:
        # Short labels so they comfortably fit in 80 columns.  We arrange
        # the buttons in two horizontal rows so they don't form a single
        # over-wide line in the right-hand pane on narrower terminals.
        #
        # Textual 0.6.x doesn't support Horizontal(wrap=...), so we use
        # two Horizontal containers stacked vertically instead of relying
        # on automatic wrapping.

        # First row of actions (project-level).
        #
        # Textual buttons support markup in their labels, so we use markup
        # to highlight the shortcut character instead of literal square
        # brackets (which are reserved for markup tags).
        with Horizontal():
            # Color the shortcut letter yellow; the rest uses the button's
            # normal style (which is already bold by default in Textual's
            # theme). Avoid additional [bold] tags so only the color
            # distinguishes the shortcut.
            yield Button("[yellow]g[/yellow]en", id="btn-generate", compact=True)          # generate Dockerfiles (g)
            yield Button("[yellow]b[/yellow]uild", id="btn-build", compact=True)           # build images (b)
            yield Button("[yellow]s[/yellow]sh", id="btn-ssh-init", compact=True)          # init SSH dir (s)
            yield Button("[yellow]c[/yellow]ache", id="btn-cache-init", compact=True)      # init git cache (c)

        # Second row of actions (task-level).
        with Horizontal():
            yield Button("[yellow]t[/yellow] new", id="btn-new-task", compact=True)        # new task (t)
            yield Button("[yellow]r[/yellow] cli", id="btn-task-run-cli", compact=True)    # run CLI for current task (r)
            yield Button("[yellow]u[/yellow] ui", id="btn-task-run-ui", compact=True)      # run UI for current task (u)
            yield Button("[yellow]d[/yellow]el", id="btn-task-delete", compact=True)       # delete current task (d)

    def on_button_pressed(self, event: Button.Pressed) -> None:  # type: ignore[override]
        btn_id = event.button.id
        app = self.app
        if not app or not btn_id:
            return

        # Call methods on the App if they exist
        mapping = {
            "btn-generate": "action_generate_dockerfiles",
            "btn-build": "action_build_images",
            "btn-ssh-init": "action_init_ssh",
            "btn-cache-init": "action_init_cache",
            "btn-new-task": "action_new_task",
            "btn-task-run-cli": "action_run_cli",
            "btn-task-run-ui": "action_run_ui",
            "btn-task-delete": "action_delete_task",
        }
        method_name = mapping.get(btn_id)
        if method_name and hasattr(app, method_name):
            getattr(app, method_name)()  # type: ignore[misc]


class TaskList(ListView):
    """Middle pane: per-project tasks."""

    class TaskSelected(Message):
        def __init__(self, project_id: str, task: TaskMeta) -> None:
            super().__init__()
            self.project_id = project_id
            self.task = task

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.project_id: Optional[str] = None
        self.tasks: List[TaskMeta] = []

    def set_tasks(self, project_id: str, tasks_meta: List[Dict[str, Any]]) -> None:
        """Populate the list from raw metadata dicts."""
        self.project_id = project_id
        self.tasks = []
        self.clear()

        for meta in tasks_meta:
            tm = TaskMeta(
                task_id=meta.get("task_id", ""),
                status=meta.get("status", "unknown"),
                mode=meta.get("mode"),
                workspace=meta.get("workspace", ""),
                ui_port=meta.get("ui_port"),
            )
            self.tasks.append(tm)

            extra_parts = []
            if tm.mode:
                extra_parts.append(f"mode={tm.mode}")
            if tm.ui_port:
                extra_parts.append(f"port={tm.ui_port}")
            extra_str = "; ".join(extra_parts)

            # This string has [...] and "mode=..." so we MUST disable markup.
            label = f"{tm.task_id} [{tm.status}"
            if extra_str:
                label += f"; {extra_str}"
            label += "]"

            self.append(ListItem(Static(label, markup=False)))

    def get_selected_task(self) -> Optional[TaskMeta]:
        idx = self.index
        if 0 <= idx < len(self.tasks):
            return self.tasks[idx]
        return None

    def on_list_view_selected(self, event: ListView.Selected) -> None:  # type: ignore[override]
        """When user selects a task row, send a semantic TaskSelected message."""
        if self.project_id is None:
            return
        task = self.get_selected_task()
        if task is not None:
            self.post_message(self.TaskSelected(self.project_id, task))


class TaskDetails(Static):
    """Bottom panel showing details for the currently selected task."""

    def set_task(self, task: Optional[TaskMeta]) -> None:
        if task is None:
            self.update("No task selected.")
            return

        lines = [
            f"Task ID:   {task.task_id}",
            f"Status:    {task.status}",
            f"Mode:      {task.mode or 'unset'}",
            f"Workspace: {task.workspace}",
        ]
        if task.ui_port:
            lines.append(f"UI URL:    http://127.0.0.1:{task.ui_port}/")

        self.update("\n".join(lines))


class ProjectState(Static):
    """Small panel summarizing infrastructure state for the active project."""

    def set_state(
        self,
        project: Optional[CodexProject],
        state: Optional[dict],
        task_count: Optional[int] = None,
    ) -> None:
        if project is None or state is None:
            self.update("No project selected.")
            return

        docker_s = "yes" if state.get("dockerfiles") else "no"
        images_s = "yes" if state.get("images") else "no"
        ssh_s = "yes" if state.get("ssh") else "no"
        cache_s = "yes" if state.get("cache") else "no"

        if task_count is None:
            tasks_line = "Tasks:     unknown"
        else:
            tasks_line = f"Tasks:     {task_count}"

        upstream = project.upstream_url or "-"

        lines = [
            f"Project:   {project.id} [{project.security_class}]",
            upstream,
            "",
            f"Dockerfiles: {docker_s}",
            f"Images:      {images_s}",
            f"SSH dir:     {ssh_s}",
            f"Git cache:   {cache_s}",
            tasks_line,
        ]

        self.update("\n".join(lines))
