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
        # Short labels so they comfortably fit in 80 columns.
        with Horizontal():
            yield Button("Gen", id="btn-generate")         # generate dockerfiles
            yield Button("Build", id="btn-build")          # build images
            yield Button("New", id="btn-new-task")         # new task
            yield Button("CLI", id="btn-task-run-cli")     # run CLI for current task
            yield Button("UI", id="btn-task-run-ui")       # run UI for current task
            yield Button("Del", id="btn-task-delete")      # delete current task

    def on_button_pressed(self, event: Button.Pressed) -> None:  # type: ignore[override]
        btn_id = event.button.id
        app = self.app
        if not app or not btn_id:
            return

        # Call methods on the App if they exist
        mapping = {
            "btn-generate": "action_generate_dockerfiles",
            "btn-build": "action_build_images",
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
