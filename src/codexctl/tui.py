#!/usr/bin/env python3
from __future__ import annotations

import sys
import shutil
from pathlib import Path
from typing import Optional


def enable_pycharm_debugger():
    import os
    if os.getenv("PYCHARM_DEBUG"):
        import pydevd_pycharm
        pydevd_pycharm.settrace(
            host='localhost',
            port=5678,
            suspend=False,   # or True if you want it to break immediately
        )



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
    from textual.widgets import Header, Button
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
        task_delete,
    )
    from .widgets import (
        ProjectList,
        ProjectActions,
        TaskList,
        TaskDetails,
        TaskMeta,
        ProjectState,
        StatusBar,
    )

    class CodexTUI(App):
        """Minimal TUI frontend for codexctl.lib."""

        CSS_PATH = None

        # Layout rules to ensure both left and right panes, and especially
        # the task list and task details on the right, are always visible.
        CSS = """
        #left-pane {
            /* Left pane: roughly one third of total width */
            width: 1fr;
            height: 1fr;
        }

        #right-pane {
            /* Right pane: roughly two thirds of total width */
            width: 2fr;
            height: 1fr;
        }

        #project-actions {
            /* Force the action bar to a small fixed height so it doesn't
             * consume the entire right pane and push the task list and
             * details off-screen. */
            height: 3;
            max-height: 3;
        }

        /* Make action buttons very compact: single-line, minimal padding. */
        ProjectActions Button {
            padding: 0 0;
        }

        #task-list {
            height: 3fr;
            min-height: 6;
        }

        #task-details {
            height: 2fr;
            min-height: 4;
        }
        """

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
            # Set on mount; used to display status / notifications.
            self._status_bar: Optional[StatusBar] = None

        # ---------- Layout ----------

        def compose(self) -> ComposeResult:
            yield Header()
            with Horizontal():
                # Left pane: project list (top) + selected project info (bottom)
                with Vertical(id="left-pane"):
                    yield ProjectList(id="project-list")
                    yield ProjectState(id="project-state")
                # Right pane: action bar + tasks + task details
                with Vertical(id="right-pane"):
                    yield ProjectActions(id="project-actions")
                    yield TaskList(id="task-list")
                    yield TaskDetails(id="task-details")
            # Custom status bar replaces Textual's default Footer so the
            # bottom line can be used for real status messages instead of
            # a long list of shortcuts (those are already shown in the
            # ProjectActions button bar).
            yield StatusBar(id="status-bar")

        async def on_mount(self) -> None:
            # Cache a reference to the status bar widget so we can update it
            # from notify() and other helpers.
            try:
                self._status_bar = self.query_one("#status-bar", StatusBar)
            except Exception:
                self._status_bar = None

            await self.refresh_projects()
            # Defer layout logging until after the first refresh cycle so
            # widgets have real sizes. This will help compare left vs right
            # panes and confirm whether the task list/details get space.
            try:
                self.call_after_refresh(self._log_layout_debug)
            except Exception:
                # call_after_refresh may not exist on very old Textual; in
                # that case we simply skip this extra logging.
                pass

        def _log_layout_debug(self) -> None:
            """Write a one-shot snapshot of key widget sizes to /tmp.

            This is for debugging why the right-hand task list/details may
            not be visible even though the widgets exist.
            """
            try:
                from pathlib import Path as _Path
                log_path = _Path("/tmp/codexctl-tui.log")
                log_path.parent.mkdir(parents=True, exist_ok=True)

                left_pane = self.query_one("#left-pane")
                right_pane = self.query_one("#right-pane")
                project_list = self.query_one("#project-list", ProjectList)
                project_state = self.query_one("#project-state", ProjectState)
                task_list = self.query_one("#task-list", TaskList)
                task_details = self.query_one("#task-details", TaskDetails)

                with log_path.open("a", encoding="utf-8") as _f:
                    _f.write("[codexctl DEBUG] layout snapshot after refresh:\n")
                    _f.write(f"  left-pane   size={left_pane.size} region={left_pane.region}\n")
                    _f.write(f"  right-pane  size={right_pane.size} region={right_pane.region}\n")
                    _f.write(f"  proj-list   size={project_list.size} region={project_list.region}\n")
                    _f.write(f"  proj-state  size={project_state.size} region={project_state.region}\n")
                    _f.write(f"  task-list   size={task_list.size} region={task_list.region}\n")
                    _f.write(f"  task-det    size={task_details.size} region={task_details.region}\n")
            except Exception:
                pass

        def _log_debug(self, message: str) -> None:
            """Append a simple debug line to the TUI log file.

            This is intentionally very small and best-effort so it never
            interferes with normal TUI behavior. It shares the same log
            path as `_log_layout_debug` for easier inspection.
            """

            try:
                from datetime import datetime as _dt
                from pathlib import Path as _Path

                log_path = _Path("/tmp/codexctl-tui.log")
                log_path.parent.mkdir(parents=True, exist_ok=True)
                ts = _dt.now().isoformat(timespec="seconds")
                with log_path.open("a", encoding="utf-8") as _f:
                    _f.write(f"[codexctl DEBUG] {ts} {message}\n")
            except Exception:
                # Logging must never break the TUI.
                pass

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

        # ---------- Status / notifications ----------

        def _set_status(self, message: str) -> None:
            """Update the bottom status bar if available."""

            if self._status_bar is not None:
                try:
                    self._status_bar.set_message(message)
                except Exception:
                    # Never let status updates break the TUI.
                    pass

        def notify(self, message: str, *args, **kwargs) -> None:  # type: ignore[override]
            """Display a notification/status message.

            We override Textual's App.notify so that notifications are
            mirrored into our custom bottom status bar while still delegating
            to the framework's native notification system when present.
            """

            self._set_status(message)

            # Best-effort delegation to the base implementation (for pop-up
            # notifications etc.). On older/newer Textual versions notify()
            # might not exist or have a different signature, so we guard it.
            try:
                super().notify(message, *args, **kwargs)  # type: ignore[misc,attr-defined]
            except Exception:
                pass

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
            """Exit the TUI cleanly.

            Older versions of this file attempted to call ``self.shutdown()``,
            but ``App`` in modern Textual does not expose such a method. The
            supported way to terminate the application programmatically is to
            call ``self.exit()``. Using ``exit()`` here avoids an
            ``AttributeError`` on quit while still delegating to Textual's
            normal shutdown/cleanup logic.
            """

            # Textual's ``App`` provides ``exit()`` rather than ``shutdown()``;
            # calling the latter would raise ``AttributeError``.
            self.exit()

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

            tid = self.current_task.task_id
            try:
                self._log_debug(
                    f"delete: start project_id={self.current_project_id} task_id={tid}"
                )
                # Let the user know we're working, since stopping containers
                # and cleaning up state can take a little while and the TUI
                # will be blocked during this operation. We keep the logic
                # simple and synchronous, but yield once to the event loop so
                # the status bar has a chance to render the message before
                # the blocking work starts.
                self.notify(f"Deleting task {tid}...")

                try:
                    import asyncio as _asyncio

                    # Yield control so Textual can process the notify() and
                    # redraw the status bar before we start the blocking
                    # delete operation.
                    await _asyncio.sleep(0)
                except Exception:
                    # If asyncio isn't available for some reason, we just
                    # proceed synchronously.
                    pass

                # Use shared library helper so containers and metadata are
                # cleaned up consistently with the CLI. This call is
                # synchronous and may take a little while if container
                # teardown or filesystem cleanup is slow, but both
                # frontends share the exact same logic here.
                self._log_debug("delete: calling task_delete()")
                task_delete(self.current_project_id, tid)
                self._log_debug("delete: task_delete() returned")
                self.notify(f"Deleted task {tid}")
            except Exception as e:
                self._log_debug(f"delete: error {e!r}")
                self.notify(f"Delete error: {e}")

            self.current_task = None
            self._log_debug("delete: refreshing tasks")
            await self.refresh_tasks()
            self._log_debug("delete: refresh_tasks() finished")

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
    enable_pycharm_debugger()
    main()
