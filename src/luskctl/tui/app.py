#!/usr/bin/env python3

import os
import sys


def enable_pycharm_debugger():
    import os

    if os.getenv("PYCHARM_DEBUG"):
        import pydevd_pycharm

        pydevd_pycharm.settrace(
            host="localhost",
            port=5678,
            suspend=False,  # or True if you want it to break immediately
        )


# Try to detect whether 'textual' is available. We avoid importing it or the
# widgets module at import time so the package can be installed without the
# optional TUI dependencies.
try:  # pragma: no cover - simple availability probe
    import importlib  # noqa: F401

    _HAS_TEXTUAL = True
except Exception:  # pragma: no cover - textual not installed
    _HAS_TEXTUAL = False


if _HAS_TEXTUAL:
    # Import textual and our widgets only when available
    from textual import on, screen
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Button, Footer, Header, Label

    from ..lib.docker import build_images, generate_dockerfiles
    from ..lib.git_gate import (
        GateStalenessInfo,
        compare_gate_vs_upstream,
        init_project_gate,
        sync_gate_branches,
    )
    from ..lib.projects import get_project_state, list_projects, load_project
    from ..lib.ssh import init_project_ssh
    from ..lib.tasks import (
        WEB_BACKENDS,
        copy_to_clipboard_detailed,
        get_clipboard_helper_status,
        get_tasks,
        get_workspace_git_diff,
        task_delete,
        task_new,
        task_run_cli,
        task_run_web,
    )
    from .widgets import (
        ProjectList,
        ProjectState,
        StatusBar,
        TaskDetails,
        TaskList,
        TaskMeta,
    )

    class ProjectActionsScreen(screen.ModalScreen[str | None]):
        """Modal screen for project actions."""

        CSS = """
        ProjectActionsScreen {
            align: center middle;
        }

        #action-dialog {
            width: 60;
            height: auto;
            border: heavy $primary;
            background: $surface;
        }

        #action-buttons {
            layout: horizontal;
            padding: 1;
        }

        Button {
            width: 100%;
            margin: 0 1;
        }
        """

        def compose(self) -> ComposeResult:
            with Horizontal(id="action-dialog"):
                with Vertical():
                    yield Label("Project Actions", id="title")
                    yield Label(" ")  # Spacer
                    with Horizontal(id="action-buttons"):
                        yield Button("[g]enerate", id="generate", variant="primary")
                        yield Button("[b]uild", id="build", variant="primary")
                        yield Button("build [a]ll", id="build_all", variant="primary")
                        yield Button("initialize [s]sh", id="init_ssh", variant="primary")
                        yield Button("sync [g]ate", id="sync_gate", variant="primary")
                    yield Label(" ")  # Spacer
                    with Horizontal():
                        yield Button("Cancel", id="cancel", variant="default")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            button_id = event.button.id
            if button_id == "cancel":
                self.dismiss(None)
            else:
                action_map = {
                    "generate": "generate",
                    "build": "build",
                    "build_all": "build_all",
                    "sync_gate": "sync_gate",
                    "init_ssh": "init_ssh",
                }
                self.dismiss(action_map.get(button_id))

    class TaskActionsScreen(screen.ModalScreen[str | None]):
        """Modal screen for task actions."""

        CSS = """
        TaskActionsScreen {
            align: center middle;
        }

        #action-dialog {
            width: 60;
            height: auto;
            border: heavy $primary;
            background: $surface;
        }

        #action-buttons {
            layout: horizontal;
            padding: 1;
        }

        Button {
            width: 100%;
            margin: 0 1;
        }
        """

        def compose(self) -> ComposeResult:
            with Horizontal(id="action-dialog"):
                with Vertical():
                    yield Label("Task Actions", id="title")
                    yield Label(" ")  # Spacer
                    with Horizontal(id="action-buttons"):
                        yield Button("[n]ew", id="new", variant="primary")
                        yield Button("[c]li", id="cli", variant="primary")
                        yield Button("[w]eb", id="web", variant="primary")
                        yield Button("[d]el", id="delete", variant="primary")
                    yield Label(" ")  # Spacer
                    with Horizontal():
                        yield Button("Cancel", id="cancel", variant="default")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            button_id = event.button.id
            if button_id == "cancel":
                self.dismiss(None)
            else:
                action_map = {"new": "new", "cli": "cli", "web": "web", "delete": "delete"}
                self.dismiss(action_map.get(button_id))

    class LuskTUI(App):
        """Redesigned TUI frontend for luskctl core modules."""

        CSS_PATH = None
        TITLE = "Luskctl TUI"

        # Layout rules for the new streamlined design with borders
        CSS = """
        Screen {
            layout: grid;
            grid-size: 2;
            grid-columns: 1fr 2fr;
            grid-rows: 1fr 3 1fr;
        }

        /* Main container borders */
        #left-pane {
            padding: 1;
        }

        #right-pane {
            padding: 1;
        }

        /* Projects section with embedded title */
        #project-list {
            border: round $primary;
            border-title-align: right;
            height: 1fr;
            min-height: 10;
        }

        /* Project details section */
        #project-state {
            border: round $primary;
            border-title-align: right;
            height: 1fr;
            min-height: 10;
            margin-top: 1;
        }

        /* Tasks section with embedded title */
        #task-list {
            border: round $primary;
            border-title-align: right;
            height: 1fr;
            min-height: 10;
        }

        /* Task details section */
        #task-details {
            border: round $primary;
            border-title-align: right;
            height: 1fr;
            min-height: 10;
            margin-top: 1;
        }

        /* Status bar styling */
        #status-bar {
            border: solid $primary;
            height: 1;
        }

        /* Task details internal layout */
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
            ("p", "show_project_actions", "Project actions"),
            ("t", "show_task_actions", "Task actions"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self.current_project_id: str | None = None
            self.current_task: TaskMeta | None = None
            # Set on mount; used to display status / notifications.
            self._status_bar: StatusBar | None = None
            # Upstream polling state
            self._staleness_info: GateStalenessInfo | None = None
            self._polling_timer = None
            self._polling_project_id: str | None = None  # Project ID the timer was started for
            self._last_notified_stale: bool = False  # Track if we already notified about staleness
            self._auto_sync_cooldown: dict[str, float] = {}  # Per-project cooldown timestamps
            # Selection persistence
            self._last_selected_project: str | None = None
            self._last_selected_tasks: dict[str, str] = {}  # project_id -> task_id

        # ---------- Layout ----------

        def compose(self) -> ComposeResult:
            # Use Textual's default Header which will show our title
            yield Header()

            # Main layout using grid
            with Horizontal():
                # Left pane: project list (top) + selected project info (bottom)
                with Vertical(id="left-pane"):
                    project_list = ProjectList(id="project-list")
                    project_list.border_title = "Projects"
                    yield project_list
                    project_state = ProjectState(id="project-state")
                    project_state.border_title = "Project Details"
                    yield project_state
                # Right pane: tasks + task details
                with Vertical(id="right-pane"):
                    task_list = TaskList(id="task-list")
                    task_list.border_title = "Tasks"
                    yield task_list
                    task_details = TaskDetails(id="task-details")
                    task_details.border_title = "Task Details"
                    yield task_details

            # Use Textual's default Footer which will show key bindings
            yield Footer()

            # Custom status bar for our messages
            yield StatusBar(id="status-bar")

        async def on_mount(self) -> None:
            # Cache a reference to the status bar widget so we can update it
            # from notify() and other helpers.
            try:
                self._status_bar = self.query_one("#status-bar", StatusBar)
            except Exception:
                self._status_bar = None

            try:
                clipboard_status = get_clipboard_helper_status()
                if not clipboard_status.available:
                    msg = "Clipboard copy unavailable: no clipboard helper found."
                    if clipboard_status.hint:
                        msg = f"{msg}\n{clipboard_status.hint}"
                    self.notify(msg, severity="warning", timeout=10)
            except Exception:
                # Clipboard helpers are best-effort; never block startup.
                pass

            # Load selection state before refreshing projects
            self._load_selection_state()

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

                log_path = _Path("/tmp/luskctl-tui.log")
                log_path.parent.mkdir(parents=True, exist_ok=True)

                left_pane = self.query_one("#left-pane")
                right_pane = self.query_one("#right-pane")
                project_list = self.query_one("#project-list", ProjectList)
                project_state = self.query_one("#project-state", ProjectState)
                task_list = self.query_one("#task-list", TaskList)
                task_details = self.query_one("#task-details", TaskDetails)

                with log_path.open("a", encoding="utf-8") as _f:
                    _f.write("[luskctl DEBUG] layout snapshot after refresh:\n")
                    _f.write(f"  left-pane   size={left_pane.size} region={left_pane.region}\n")
                    _f.write(f"  right-pane  size={right_pane.size} region={right_pane.region}\n")
                    _f.write(
                        f"  proj-list   size={project_list.size} region={project_list.region}\n"
                    )
                    _f.write(
                        f"  proj-state  size={project_state.size} region={project_state.region}\n"
                    )
                    _f.write(f"  task-list   size={task_list.size} region={task_list.region}\n")
                    _f.write(
                        f"  task-det    size={task_details.size} region={task_details.region}\n"
                    )
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

                log_path = _Path("/tmp/luskctl-tui.log")
                log_path.parent.mkdir(parents=True, exist_ok=True)
                ts = _dt.now().isoformat(timespec="seconds")
                with log_path.open("a", encoding="utf-8") as _f:
                    _f.write(f"[luskctl DEBUG] {ts} {message}\n")
            except Exception:
                # Logging must never break the TUI.
                pass

        def _load_selection_state(self) -> None:
            """Load last selected project and tasks from persistent storage."""
            try:
                import json
                from pathlib import Path as _Path

                state_path = _Path("~/.luskctl-tui-state.json").expanduser()
                if state_path.exists():
                    with state_path.open("r", encoding="utf-8") as f:
                        state = json.load(f)
                        self._last_selected_project = state.get("last_project")
                        self._last_selected_tasks = state.get("last_tasks", {})
            except Exception:
                # If loading fails, just start with empty state
                self._last_selected_project = None
                self._last_selected_tasks = {}

        def _save_selection_state(self) -> None:
            """Save current selection state to persistent storage."""
            try:
                import json
                from pathlib import Path as _Path

                state_path = _Path("~/.luskctl-tui-state.json").expanduser()
                state = {
                    "last_project": self.current_project_id,
                    "last_tasks": self._last_selected_tasks,
                }
                with state_path.open("w", encoding="utf-8") as f:
                    json.dump(state, f)
            except Exception:
                # If saving fails, just ignore - it's not critical
                pass

        def _prompt_ui_backend(self) -> str:
            backends = list(WEB_BACKENDS)
            # Check DEFAULT_AGENT first, fall back to LUSKUI_BACKEND
            default = os.environ.get("DEFAULT_AGENT", "").strip().lower()
            if not default:
                default = os.environ.get("LUSKUI_BACKEND", "").strip().lower()
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
                # Try to restore last selected project, fall back to first project
                last_project = self._last_selected_project
                if last_project and any(p.id == last_project for p in projects):
                    self.current_project_id = last_project
                    proj_widget.select_project(self.current_project_id)
                elif self.current_project_id is None:
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
                # Try to restore last selected task for this project
                last_task_id = self._last_selected_tasks.get(self.current_project_id)
                if last_task_id:
                    # Find the task with the matching ID
                    for idx, task in enumerate(task_list.tasks):
                        if task.task_id == last_task_id:
                            task_list.index = idx
                            self.current_task = task
                            break
                    else:
                        # Task not found, select the newest task
                        task_list.index = 0
                        self.current_task = task_list.tasks[0]
                else:
                    # No remembered task, select the newest task
                    task_list.index = 0
                    self.current_task = task_list.tasks[0]
            else:
                self.current_task = None

            task_details = self.query_one("#task-details", TaskDetails)
            if self.current_task is None:
                # Be explicit so users understand why the right side is empty.
                task_details.update(
                    "No tasks for this project yet.\nPress 't' to create a new task."
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

        def _refresh_project_state(self, task_count: int | None = None) -> None:
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

            Only polls for gatekeeping projects with polling enabled and a gate initialized.
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

            # Only poll for gatekeeping projects with polling enabled
            if project.security_class != "gatekeeping":
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
                interval_seconds, self._poll_upstream, name="upstream_polling"
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

        async def _sync_worker(
            self, project_id: str, branches: list = None, is_auto: bool = False
        ) -> None:
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
                if project.security_class != "gatekeeping":
                    self.notify("Sync only available for gatekeeping projects.")
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
            """Called when user selects a project in the list."""
            self.current_project_id = message.project_id
            # Save the project selection
            self._last_selected_project = self.current_project_id
            self._save_selection_state()

            await self.refresh_tasks()
            # Start polling for the newly selected project
            self._start_upstream_polling()

        @on(TaskList.TaskSelected)
        async def handle_task_selected(self, message: TaskList.TaskSelected) -> None:
            """Called when user selects a task in the list."""
            self.current_project_id = message.project_id
            self.current_task = message.task

            # Save the task selection for this project
            if self.current_project_id and self.current_task:
                self._last_selected_tasks[self.current_project_id] = self.current_task.task_id
                self._save_selection_state()

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
            result = copy_to_clipboard_detailed(diff)
            if result.ok:
                self.notify(f"Git diff copied to clipboard ({len(diff)} characters)")
            else:
                msg = result.error or "Failed to copy to clipboard."
                if result.hint:
                    msg = f"{msg}\n{result.hint}"
                self.notify(msg)

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

        async def action_show_project_actions(self) -> None:
            """Show modal dialog with project actions."""
            await self.push_screen(ProjectActionsScreen(), self._on_project_action_screen_result)

        async def action_show_task_actions(self) -> None:
            """Show modal dialog with task actions."""
            await self.push_screen(TaskActionsScreen(), self._on_task_action_screen_result)

        async def _on_project_action_screen_result(self, result: str | None) -> None:
            """Handle result from project actions screen."""
            if result:
                await self._handle_project_action(result)

        async def _on_task_action_screen_result(self, result: str | None) -> None:
            """Handle result from task actions screen."""
            if result:
                await self._handle_task_action(result)

        async def _handle_project_action(self, action: str) -> None:
            """Handle project actions."""
            if action == "generate":
                await self.action_generate_dockerfiles()
            elif action == "build":
                await self.action_build_images()
            elif action == "build_all":
                await self._action_build_all_images()
            elif action == "init_ssh":
                await self.action_init_ssh()
            elif action == "sync_gate":
                await self._action_sync_gate()

        async def _handle_task_action(self, action: str) -> None:
            """Handle task actions."""
            if action == "new":
                await self.action_new_task()
            elif action == "cli":
                await self.action_run_cli()
            elif action == "web":
                await self._action_run_web()
            elif action == "delete":
                await self.action_delete_task()

        async def _action_build_all_images(self) -> None:
            """Build all project images."""
            if not self.current_project_id:
                self.notify("No project selected.")
                return
            with self.suspend():
                try:
                    # This would need to be implemented in the docker module
                    print("Building all images...")
                    # build_all_images(self.current_project_id)
                except SystemExit as e:
                    print(f"Error: {e}")
                input("\n[Press Enter to return to LuskTUI] ")
            self.notify(f"Built all images for {self.current_project_id}")
            self._refresh_project_state()

        async def _action_sync_gate(self) -> None:
            """Sync gate (init if doesn't exist, sync if exists)."""
            if not self.current_project_id:
                self.notify("No project selected.")
                return

            try:
                project = load_project(self.current_project_id)
                if project.security_class != "gatekeeping":
                    self.notify("Sync only available for gatekeeping projects.")
                    return

                self.notify("Syncing gate...")

                # Run sync in background worker
                self.run_worker(
                    self._sync_gate_worker(self.current_project_id),
                    name="gate_sync",
                    exclusive=True,
                )

            except Exception as e:
                self.notify(f"Sync error: {e}")

        async def _sync_gate_worker(self, project_id: str) -> None:
            """Background worker to sync gate (init if needed)."""
            try:
                # Check if gate exists
                project = load_project(project_id)
                gate_exists = project.gate_path.exists()

                if not gate_exists:
                    # Init gate
                    result = init_project_gate(project_id)
                    if project_id == self.current_project_id:
                        self.notify(f"Gate initialized at {result['path']}")
                else:
                    # Sync gate
                    result = sync_gate_branches(project_id)
                    if result["success"]:
                        if project_id == self.current_project_id:
                            self.notify("Gate synced from upstream")
                    else:
                        if project_id == self.current_project_id:
                            self.notify(f"Gate sync failed: {', '.join(result['errors'])}")

                # Refresh state after gate operation
                if project_id == self.current_project_id:
                    self._refresh_project_state()

            except Exception as e:
                if project_id == self.current_project_id:
                    self.notify(f"Gate operation error: {e}")

        async def _action_run_web(self) -> None:
            """Run web UI for current task."""
            if not self.current_project_id or not self.current_task:
                self.notify("No task selected.")
                return
            tid = self.current_task.task_id
            with self.suspend():
                try:
                    backend = self._prompt_ui_backend()
                    print(
                        f"Starting Web UI for {self.current_project_id}/{tid} (backend: {backend})...\n"
                    )
                    task_run_web(self.current_project_id, tid, backend=backend)
                except SystemExit as e:
                    print(f"Error: {e}")
                input("\n[Press Enter to return to LuskTUI] ")
            await self.refresh_tasks()

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
                input("\n[Press Enter to return to LuskTUI] ")
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
                input("\n[Press Enter to return to LuskTUI] ")
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
                input("\n[Press Enter to return to LuskTUI] ")

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
                input("\n[Press Enter to return to LuskTUI] ")

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
                input("\n[Press Enter to return to LuskTUI] ")
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
                input("\n[Press Enter to return to LuskTUI] ")
            await self.refresh_tasks()

        async def action_run_web(self) -> None:
            """Public action for running web UI (delegates to _action_run_web)."""
            await self._action_run_web()

        async def action_delete_task(self) -> None:
            if not self.current_project_id or not self.current_task:
                self.notify("No task selected.")
                return

            tid = self.current_task.task_id
            try:
                self._log_debug(f"delete: start project_id={self.current_project_id} task_id={tid}")
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

            result = copy_to_clipboard_detailed(diff)
            if result.ok:
                self.notify(f"Git diff vs {label} copied to clipboard ({len(diff)} characters)")
            else:
                msg = result.error or "Failed to copy to clipboard."
                if result.hint:
                    msg = f"{msg}\n{result.hint}"
                self.notify(msg)

        async def action_copy_diff_head(self) -> None:
            """Copy git diff vs HEAD to clipboard."""
            await self._copy_diff_to_clipboard("HEAD", "HEAD")

        async def action_copy_diff_prev(self) -> None:
            """Copy git diff vs previous commit to clipboard."""
            await self._copy_diff_to_clipboard("PREV", "PREV")

    def main() -> None:
        LuskTUI().run()

else:

    def main() -> None:
        print(
            "luskctl TUI requires the 'textual' package.\n"
            "Install it with: pip install 'luskctl[tui]'",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    enable_pycharm_debugger()
    main()
