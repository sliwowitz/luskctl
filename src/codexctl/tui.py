#!/usr/bin/env python3
from __future__ import annotations

import sys
import shutil
from pathlib import Path
from typing import Optional


# Try to detect whether 'textual' is available. We avoid importing it or the
# widgets module at import time so the package can be installed without the
# optional TUI dependencies.
try:  # pragma: no cover - simple availability probe
    import importlib  # noqa: F401
    import textual  # type: ignore
    _HAS_TEXTUAL = True
except Exception:  # pragma: no cover - textual not installed
    _HAS_TEXTUAL = False


if _HAS_TEXTUAL:
    # Import textual and our widgets only when available
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
        init_project_ssh,
        init_project_cache,
        get_project_state,
    )
    from .widgets import (
        ProjectList,
        ProjectActions,
        TaskList,
        TaskDetails,
        TaskMeta,
        ProjectState,
    )

    class CodexTUI(App):
        """Minimal TUI frontend for codexctl.lib."""

        CSS_PATH = None

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("g", "generate_dockerfiles", "Generate Dockerfiles"),
            ("b", "build_images", "Build images"),
            ("s", "init_ssh", "Init SSH"),
            ("c", "init_cache", "Init cache"),
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
                # Left pane: project list (top) + selected project info (bottom)
                with Vertical():
                    yield ProjectList(id="project-list")
                    yield ProjectState(id="project-state")
                # Right pane: action bar + tasks + task details
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
                # No projects means no meaningful project state.
                state_widget = self.query_one("#project-state", ProjectState)
                state_widget.set_state(None, None, None)

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
            if self.current_task is None:
                # Be explicit so users understand why the right side is empty.
                task_details.update(
                    "No tasks for this project yet.\n"
                    "Press 't' to create a new task."
                )
            else:
                task_details.set_task(self.current_task)

            # Update project state panel (Dockerfiles/images/SSH/cache + task count)
            self._refresh_project_state(task_count=len(task_list.tasks))

        def _refresh_project_state(self, task_count: Optional[int] = None) -> None:
            """Update the small project state summary panel.

            This is called whenever the current project changes or when actions
            that affect infrastructure state (generate/build/ssh/cache) finish.
            """
            state_widget = self.query_one("#project-state", ProjectState)

            if not self.current_project_id:
                state_widget.set_state(None, None, None)
                return

            try:
                project = load_project(self.current_project_id)
                state = get_project_state(self.current_project_id)
            except SystemExit as e:
                # Surface configuration/state problems directly in the TUI.
                state_widget.update(f"Project state error: {e}")
                return

            state_widget.set_state(project, state, task_count)

        # ---------- Selection handlers (from widgets) ----------

        @on(ProjectList.ProjectSelected)
        async def handle_project_selected(self, message: ProjectList.ProjectSelected) -> None:
            """Called when user activates a project in the list."""
            self.current_project_id = message.project_id
            await self.refresh_tasks()
            # After activating a project, move focus to the task list so the user
            # can immediately navigate and run tasks.
            task_list = self.query_one("#task-list", TaskList)
            self.set_focus(task_list)

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
            self._refresh_project_state()

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
            self._refresh_project_state()

        async def action_init_ssh(self) -> None:
            """Initialize the per-project SSH directory and keypair."""
            if not self.current_project_id:
                self.notify("No project selected.")
                return

            with self.suspend():
                try:
                    init_project_ssh(self.current_project_id)
                except SystemExit as e:
                    print(f"Error: {e}")
                input("\n[Press Enter to return to CodexTUI] ")

            self.notify(f"Initialized SSH dir for {self.current_project_id}")
            self._refresh_project_state()

        async def action_init_cache(self) -> None:
            """Initialize or update the git cache mirror for the project."""
            if not self.current_project_id:
                self.notify("No project selected.")
                return

            with self.suspend():
                try:
                    res = init_project_cache(self.current_project_id)
                    print(
                        f"Cache ready at {res['path']} "
                        f"(upstream: {res['upstream_url']}; created: {res['created']})"
                    )
                except SystemExit as e:
                    print(f"Error: {e}")
                input("\n[Press Enter to return to CodexTUI] ")

            self.notify(f"Git cache initialized for {self.current_project_id}")
            self._refresh_project_state()

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

else:
    def main() -> None:
        print(
            "codexctl TUI requires the 'textual' package.\n"
            "Install it with: pip install 'codexctl[tui]'",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
