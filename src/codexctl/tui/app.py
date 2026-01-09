#!/usr/bin/env python3
from __future__ import annotations

import os
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

    from ..lib.config import state_root
    from ..lib.docker import build_images, generate_dockerfiles
    from ..lib.git_gate import (
        init_project_gate,
        compare_gate_vs_upstream,
        sync_gate_branches,
        GateStalenessInfo,
    )
    from ..lib.projects import get_project_state, list_projects, load_project
    from ..lib.ssh import init_project_ssh
    from ..lib.tasks import (
        UI_BACKENDS,
        copy_to_clipboard,
        get_tasks,
        get_workspace_git_diff,
        task_delete,
        task_new,
        task_run_cli,
        task_run_ui,
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
        """Minimal TUI frontend for codexctl core modules."""

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
            min-height: 6;
        }

        # Task details internal layout
        #task-details-content {
            height: 1fr;
        }
        #task-details-actions {
            height: auto;
            margin-top: 1;
        }
        """

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("g", "generate_dockerfiles", "Generate Dockerfiles"),
            ("b", "build_images", "Build images"),
            ("s", "init_ssh", "Init SSH"),
            ("c", "init_gate", "Init gate"),
            ("S", "sync_gate", "Sync gate"),
            ("t", "new_task", "New task"),
            ("r", "run_cli", "Run CLI"),
            ("u", "run_ui", "Run UI"),
            ("d", "delete_task", "Delete task"),
            ("y", "copy_diff_head", "Copy diff vs HEAD"),
            ("Y", "copy_diff_prev", "Copy diff vs PREV"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self.current_project_id: Optional[str] = None
            self.current_task: Optional[TaskMeta] = None
            # Set on mount; used to display status / notifications.
            self._status_bar: Optional[StatusBar] = None
            # Upstream polling state
            self._staleness_info: Optional[GateStalenessInfo] = None
            self._polling_timer = None
            self._polling_project_id: Optional[str] = None  # Project ID the timer was started for
            self._last_notified_stale: bool = False  # Track if we already notified about staleness
            self._auto_sync_cooldown: dict[str, float] = {}  # Per-project cooldown timestamps

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

        def _prompt_ui_backend(self) -> str:
            backends = list(UI_BACKENDS)
            # Check WEBUI_BACKEND first (new name), fall back to CODEXUI_BACKEND for compatibility
            default = os.environ.get("WEBUI_BACKEND", "").strip().lower()
            if not default:
                default = os.environ.get("CODEXUI_BACKEND", "").strip().lower()
            if not default:
                default = backends[0] if backends else "codex"

            print("Select UI backend:")
            for idx, backend in enumerate(backends, start=1):
                label = backend
                if backend == default:
                    label += " (default)"
                print(f"  {idx}) {label}")

            choice = input(f"Backend [{default}]: ").strip()
            if not choice:
                return default
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(backends):
                    return backends[idx - 1]
                return default
            return choice.lower()

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
                # Start upstream polling for the selected project
                self._start_upstream_polling()
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

            state_widget.set_state(project, state, task_count, self._staleness_info)

        # ---------- Upstream polling ----------

        def _start_upstream_polling(self) -> None:
            """Start background polling for upstream changes.

            Only polls for gatekept projects with polling enabled and a gate initialized.
            """
            self._stop_upstream_polling()  # Stop any existing timer
            self._staleness_info = None
            self._last_notified_stale = False

            if not self.current_project_id:
                return

            try:
                project = load_project(self.current_project_id)
            except SystemExit:
                return

            # Only poll for gatekept projects with polling enabled
            if project.security_class != "gatekept":
                return
            if not project.upstream_polling_enabled:
                return
            if not project.gate_path.exists():
                return

            interval_seconds = project.upstream_polling_interval_minutes * 60
            self._polling_project_id = self.current_project_id

            # Perform initial poll immediately (in background worker)
            self._poll_upstream()

            # Schedule recurring polls
            self._polling_timer = self.set_interval(
                interval_seconds,
                self._poll_upstream,
                name="upstream_polling"
            )

        def _stop_upstream_polling(self) -> None:
            """Stop the upstream polling timer."""
            if self._polling_timer is not None:
                self._polling_timer.stop()
                self._polling_timer = None
            self._polling_project_id = None

        def _poll_upstream(self) -> None:
            """Check upstream for changes and update staleness info.

            Runs the actual comparison in a background worker to avoid blocking the UI.
            """
            project_id = self._polling_project_id
            if not project_id or project_id != self.current_project_id:
                # Project changed since timer was started, skip this poll
                return

            self._log_debug(f"polling upstream for {project_id}")
            # Run blocking git operation in background worker
            self.run_worker(
                self._poll_upstream_worker(project_id),
                name="poll_upstream",
                exclusive=True,  # Cancel any previous poll still running
            )

        async def _poll_upstream_worker(self, project_id: str) -> None:
            """Background worker to check upstream (runs in thread pool)."""
            import asyncio

            try:
                # Run blocking call in thread pool
                staleness = await asyncio.get_event_loop().run_in_executor(
                    None, compare_gate_vs_upstream, project_id
                )

                # Validate project hasn't changed while we were polling
                if project_id != self.current_project_id:
                    return

                self._on_staleness_updated(project_id, staleness)

            except Exception as e:
                self._log_debug(f"upstream poll error: {e}")

        def _on_staleness_updated(self, project_id: str, staleness: GateStalenessInfo) -> None:
            """Handle updated staleness info."""
            # Double-check project hasn't changed
            if project_id != self.current_project_id:
                return

            self._staleness_info = staleness

            # Only update notification state for valid (non-error) comparisons
            if staleness.error:
                # Don't change notification state on errors - preserve previous state
                pass
            elif staleness.is_stale and not self._last_notified_stale:
                behind_str = ""
                if staleness.commits_behind is not None:
                    behind_str = f" ({staleness.commits_behind} commits behind)"
                self.notify(f"Gate is behind upstream on {staleness.branch}{behind_str}")
                self._last_notified_stale = True

                # Trigger auto-sync if enabled (with cooldown check)
                self._maybe_auto_sync(project_id)
            elif not staleness.is_stale:
                # Only reset when we have confirmed up-to-date status
                self._last_notified_stale = False

            # Refresh the project state display
            self._refresh_project_state()

        def _maybe_auto_sync(self, project_id: str) -> None:
            """Trigger auto-sync if enabled for this project.

            Runs sync in background worker to avoid blocking UI.
            Implements cooldown to prevent sync loops.
            """
            import time

            if not project_id or project_id != self.current_project_id:
                return

            # Check cooldown (5 minute minimum between auto-syncs per project)
            now = time.time()
            cooldown_until = self._auto_sync_cooldown.get(project_id, 0)
            if now < cooldown_until:
                self._log_debug("auto-sync skipped: cooldown active")
                return

            try:
                project = load_project(project_id)
                if not project.auto_sync_enabled:
                    return

                # Set cooldown before starting sync (5 minutes)
                self._auto_sync_cooldown[project_id] = now + 300

                self._log_debug(f"auto-syncing gate for {project_id}")
                self.notify("Auto-syncing gate from upstream...")

                # Run sync in background worker
                branches = project.auto_sync_branches or None
                self.run_worker(
                    self._sync_worker(project_id, branches, is_auto=True),
                    name="auto_sync",
                    exclusive=True,
                )

            except Exception as e:
                self._log_debug(f"auto-sync error: {e}")

        async def _sync_worker(self, project_id: str, branches: list = None, is_auto: bool = False) -> None:
            """Background worker to sync gate from upstream."""
            import asyncio

            try:
                # Run blocking sync in thread pool
                result = await asyncio.get_event_loop().run_in_executor(
                    None, sync_gate_branches, project_id, branches
                )

                # Validate project hasn't changed
                if project_id != self.current_project_id:
                    return

                if result["success"]:
                    label = "Auto-synced" if is_auto else "Synced"
                    self.notify(f"{label} gate from upstream")

                    # Re-check staleness after sync
                    staleness = await asyncio.get_event_loop().run_in_executor(
                        None, compare_gate_vs_upstream, project_id
                    )

                    if project_id == self.current_project_id:
                        self._staleness_info = staleness
                        # Only reset notification flag if we're actually up-to-date now
                        if not staleness.is_stale and not staleness.error:
                            self._last_notified_stale = False
                        self._refresh_project_state()
                else:
                    label = "Auto-sync" if is_auto else "Sync"
                    self.notify(f"{label} failed: {', '.join(result['errors'])}")

            except Exception as e:
                label = "Auto-sync" if is_auto else "Sync"
                self.notify(f"{label} error: {e}")

        async def action_sync_gate(self) -> None:
            """Manually sync gate from upstream."""
            if not self.current_project_id:
                self.notify("No project selected.")
                return

            try:
                project = load_project(self.current_project_id)
                if project.security_class != "gatekept":
                    self.notify("Sync only available for gatekept projects.")
                    return

                self.notify("Syncing gate from upstream...")

                # Run sync in background worker
                self.run_worker(
                    self._sync_worker(self.current_project_id, None, is_auto=False),
                    name="manual_sync",
                    exclusive=True,
                )

            except Exception as e:
                self.notify(f"Sync error: {e}")

        # ---------- Selection handlers (from widgets) ----------

        @on(ProjectList.ProjectSelected)
        async def handle_project_selected(self, message: ProjectList.ProjectSelected) -> None:
            """Called when user activates a project in the list."""
            self.current_project_id = message.project_id
            await self.refresh_tasks()
            # Start polling for the newly selected project
            self._start_upstream_polling()


        @on(TaskList.TaskSelected)
        async def handle_task_selected(self, message: TaskList.TaskSelected) -> None:
            """Called when user activates a task in the list."""
            self.current_project_id = message.project_id
            self.current_task = message.task
            details = self.query_one("#task-details", TaskDetails)
            details.set_task(self.current_task)

        @on(TaskDetails.CopyDiffRequested)
        async def handle_copy_diff_requested(self, message: TaskDetails.CopyDiffRequested) -> None:
            """Called when user requests to copy git diff to clipboard."""
            if not self.current_project_id or not self.current_task:
                self.notify("No task selected.")
                return

            task_id = self.current_task.task_id
            diff = get_workspace_git_diff(self.current_project_id, task_id, message.diff_type)

            if diff is None:
                self.notify("Failed to get git diff. Is this a git repository?")
                return

            if diff == "":
                self.notify("No changes to copy (working tree clean).")
                return

            # Try to copy to clipboard
            success = copy_to_clipboard(diff)
            if success:
                self.notify(f"Git diff copied to clipboard ({len(diff)} characters)")
            else:
                self.notify("Failed to copy to clipboard. Clipboard utility not found.")

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
            # Stop upstream polling before exit
            self._stop_upstream_polling()

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

        async def action_init_gate(self) -> None:
            """Initialize or update the git gate mirror for the project."""
            if not self.current_project_id:
                self.notify("No project selected.")
                return

            with self.suspend():
                try:
                    res = init_project_gate(self.current_project_id)
                    print(
                        f"Gate ready at {res['path']} "
                        f"(upstream: {res['upstream_url']}; created: {res['created']})"
                    )
                except SystemExit as e:
                    print(f"Error: {e}")
                input("\n[Press Enter to return to CodexTUI] ")

            self.notify(f"Git gate initialized for {self.current_project_id}")
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
                    backend = self._prompt_ui_backend()
                    print(
                        f"Starting UI for {self.current_project_id}/{tid} "
                        f"(backend: {backend})...\n"
                    )
                    task_run_ui(self.current_project_id, tid, backend=backend)
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

        async def _copy_diff_to_clipboard(self, git_ref: str, label: str) -> None:
            """Common helper to copy a git diff to the clipboard."""
            if not self.current_project_id or not self.current_task:
                self.notify("No task selected.")
                return

            task_id = self.current_task.task_id
            diff = get_workspace_git_diff(self.current_project_id, task_id, git_ref)

            if diff is None:
                self.notify("Failed to get git diff. Is this a git repository?")
                return

            if diff == "":
                self.notify("No changes to copy (working tree clean).")
                return

            success = copy_to_clipboard(diff)
            if success:
                self.notify(f"Git diff vs {label} copied to clipboard ({len(diff)} characters)")
            else:
                self.notify("Failed to copy to clipboard. Clipboard utility not found.")

        async def action_copy_diff_head(self) -> None:
            """Copy git diff vs HEAD to clipboard."""
            await self._copy_diff_to_clipboard("HEAD", "HEAD")

        async def action_copy_diff_prev(self) -> None:
            """Copy git diff vs previous commit to clipboard."""
            await self._copy_diff_to_clipboard("PREV", "PREV")

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
