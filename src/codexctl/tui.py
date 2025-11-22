#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Button
from textual.containers import Horizontal, Vertical
from textual import on

from .lib import (
    list_projects,
    get_tasks,
    task_new,
    task_run_cli,
    task_run_ui,
    generate_dockerfiles,
    build_images,
    load_project,
    state_root,
)
from .widgets import ProjectList, ProjectActions, TaskList, TaskDetails, TaskMeta


class CodexTUI(App):
    """Minimal TUI frontend for codexctl.lib."""

    CSS_PATH = None

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("g", "generate_dockerfiles", "Generate Dockerfiles"),
        ("b", "build_images", "Build images"),
        ("t", "new_task", "New task"),
        ("r", "run_cli", "Run CLI"),
        ("u", "run_ui", "Run UI"),
        ("d", "delete_task", "Delete task"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.current_project_id: Optional[str] = None
        self.current_task: Optional[TaskMeta] = None

    # ---------- Layout ----------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            # Left: project list
            yield ProjectList(id="project-list")
            # Right: actions + tasks + details
            with Vertical():
                yield ProjectActions(id="project-actions")
                yield TaskList(id="task-list")
                yield TaskDetails(id="task-details")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_projects()

    # ---------- Helpers ----------

    async def refresh_projects(self) -> None:
        proj_widget = self.query_one("#project-list", ProjectList)
        projects = list_projects()
        proj_widget.set_projects(projects)

        if projects:
            if self.current_project_id is None:
                self.current_project_id = projects[0].id
                proj_widget.select_project(self.current_project_id)
            await self.refresh_tasks()
        else:
            self.current_project_id = None
            task_list = self.query_one("#task-list", TaskList)
            task_list.set_tasks("", [])
            task_details = self.query_one("#task-details", TaskDetails)
            task_details.set_task(None)

    async def refresh_tasks(self) -> None:
        if not self.current_project_id:
            return
        tasks_meta = get_tasks(self.current_project_id, reverse=True)
        task_list = self.query_one("#task-list", TaskList)
        task_list.set_tasks(self.current_project_id, tasks_meta)

        if task_list.tasks:
            task_list.index = 0
            self.current_task = task_list.tasks[0]
        else:
            self.current_task = None

        task_details = self.query_one("#task-details", TaskDetails)
        task_details.set_task(self.current_task)

    # ---------- Selection handlers (from widgets) ----------

    @on(ProjectList.ProjectSelected)
    async def handle_project_selected(self, message: ProjectList.ProjectSelected) -> None:
        """Called when user activates a project in the list."""
        self.current_project_id = message.project_id
        await self.refresh_tasks()

    @on(TaskList.TaskSelected)
    async def handle_task_selected(self, message: TaskList.TaskSelected) -> None:
        """Called when user activates a task in the list."""
        self.current_project_id = message.project_id
        self.current_task = message.task
        details = self.query_one("#task-details", TaskDetails)
        details.set_task(self.current_task)

    # ---------- Button presses (forwarded from ProjectActions) ----------

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        # ProjectActions already calls our action_* methods directly; this is just a safety net
        pass

    # ---------- Actions (keys + called from buttons) ----------

    async def action_quit(self) -> None:
        await self.shutdown()

    async def action_generate_dockerfiles(self) -> None:
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        # Suspend TUI, run command with raw stdout, wait for keypress, resume
        with self.suspend():
            try:
                generate_dockerfiles(self.current_project_id)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to CodexTUI] ")
        self.notify(f"Generated Dockerfiles for {self.current_project_id}")

    async def action_build_images(self) -> None:
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        with self.suspend():
            try:
                build_images(self.current_project_id)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to CodexTUI] ")
        self.notify(f"Built images for {self.current_project_id}")

    async def action_new_task(self) -> None:
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        with self.suspend():
            try:
                task_new(self.current_project_id)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to CodexTUI] ")
        await self.refresh_tasks()
        self.notify("Task created.")

    async def action_run_cli(self) -> None:
        if not self.current_project_id or not self.current_task:
            self.notify("No task selected.")
            return
        tid = self.current_task.task_id
        with self.suspend():
            try:
                print(f"Running CLI for {self.current_project_id}/{tid}...\n")
                task_run_cli(self.current_project_id, tid)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to CodexTUI] ")
        await self.refresh_tasks()

    async def action_run_ui(self) -> None:
        if not self.current_project_id or not self.current_task:
            self.notify("No task selected.")
            return
        tid = self.current_task.task_id
        with self.suspend():
            try:
                print(f"Starting UI for {self.current_project_id}/{tid}...\n")
                task_run_ui(self.current_project_id, tid)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to CodexTUI] ")
        await self.refresh_tasks()

    async def action_delete_task(self) -> None:
        if not self.current_project_id or not self.current_task:
            self.notify("No task selected.")
            return

        project = load_project(self.current_project_id)
        tid = self.current_task.task_id

        workspace = Path(self.current_task.workspace)
        meta_dir = state_root() / "projects" / project.id / "tasks"
        meta_path = meta_dir / f"{tid}.yml"

        try:
            if workspace.is_dir():
                shutil.rmtree(workspace)
            if meta_path.is_file():
                meta_path.unlink()
            self.notify(f"Deleted task {tid}")
        except Exception as e:
            self.notify(f"Delete error: {e}")

        self.current_task = None
        await self.refresh_tasks()


def main() -> None:
    CodexTUI().run()


if __name__ == "__main__":
    main()
