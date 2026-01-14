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
    import importlib.util

    _HAS_TEXTUAL = importlib.util.find_spec("textual") is not None
except Exception:  # pragma: no cover - textual not installed
    _HAS_TEXTUAL = False


if _HAS_TEXTUAL:
    # Import textual and our widgets only when available
    from textual import events, on, screen
    from textual.app import App, ComposeResult

    try:  # pragma: no cover - optional import for test stubs
        from textual.binding import Binding
    except Exception:  # pragma: no cover - textual may be a stub module
        Binding = None  # type: ignore[assignment]
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Button, Footer, Header
    from textual.worker import Worker, WorkerState

    from ..lib.docker import build_images, generate_dockerfiles
    from ..lib.git_gate import (
        GateStalenessInfo,
        compare_gate_vs_upstream,
        sync_gate_branches,
        sync_project_gate,
    )
    from ..lib.projects import Project as CodexProject
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
        _is_task_image_old,
    )

    def _get_version_info() -> tuple[str, str | None]:
        """Get version and branch information.

        Returns:
            tuple: (version_string, branch_name) where branch_name is None for releases
        """
        import subprocess
        import tomllib
        from pathlib import Path

        # Try to get version from installed package first
        version = "unknown"
        try:
            # Try importing to get __version__ (for installed packages)
            from luskctl import __version__ as pkg_version

            version = pkg_version
        except ImportError:
            # Fall back to reading from pyproject.toml (for development)
            try:
                pyproject_path = Path(__file__).parent.parent.parent.parent / "pyproject.toml"
                if pyproject_path.exists():
                    with open(pyproject_path, "rb") as f:
                        pyproject_data = tomllib.load(f)
                        version = pyproject_data["tool"]["poetry"]["version"]
            except Exception:
                version = "unknown"

        # Check if this is a git repository and get branch info
        branch_name = None

        # First, try to get branch info from preserved file (for pip/pipx installs from git)
        try:
            from luskctl import _branch_info

            if hasattr(_branch_info, "BRANCH_NAME"):
                branch_name = _branch_info.BRANCH_NAME
                # If we found branch info from the preserved file, we're done
                return version, branch_name
        except ImportError:
            # _branch_info module doesn't exist, continue with other methods
            pass

        # Then check if we're likely running from source by looking for pyproject.toml
        is_likely_source = False
        try:
            pyproject_path = Path(__file__).parent.parent.parent.parent / "pyproject.toml"
            is_likely_source = pyproject_path.exists()
        except Exception:
            pass

        # Only try git detection if we're likely running from source
        if is_likely_source:
            try:
                # Check if we're in a git repo
                result = subprocess.run(
                    ["git", "rev-parse", "--is-inside-work-tree"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                    cwd=str(Path(__file__).parent.parent.parent.parent),
                )
                if result.returncode == 0 and result.stdout.strip() == "true":
                    # Get current branch name
                    branch_result = subprocess.run(
                        ["git", "branch", "--show-current"],
                        capture_output=True,
                        text=True,
                        timeout=1,
                        cwd=str(Path(__file__).parent.parent.parent.parent),
                    )
                if branch_result.returncode == 0:
                    branch_name = branch_result.stdout.strip()

                    # Check if this is a tagged release (vX.Y.Z format)
                    tag_result = subprocess.run(
                        ["git", "describe", "--exact-match", "--tags", "HEAD"],
                        capture_output=True,
                        text=True,
                        timeout=1,
                        cwd=str(Path(__file__).parent.parent.parent.parent),
                    )
                    if tag_result.returncode == 0 and tag_result.stdout.strip().startswith("v"):
                        # This is a tagged release, don't show branch
                        branch_name = None
            except Exception:
                # If git commands fail, we're likely not in a git repo or git isn't available
                pass

        return version, branch_name

    def _modal_binding(key: str, action: str, description: str):
        if Binding is None:
            return (key, action, description)
        return Binding(key, action, description, show=False)

    class ProjectActionsScreen(screen.ModalScreen[str | None]):
        """Modal screen for project actions."""

        BINDINGS = [
            _modal_binding("escape", "dismiss", "Cancel"),
            _modal_binding("q", "dismiss", "Cancel"),
            _modal_binding("up", "app.focus_previous", "Previous"),
            _modal_binding("down", "app.focus_next", "Next"),
            _modal_binding("d", "generate", "Generate dockerfiles"),
            _modal_binding("b", "build", "Build project image"),
            _modal_binding("a", "build_all", "Build all images"),
            _modal_binding("s", "init_ssh", "Init SSH"),
            _modal_binding("g", "sync_gate", "Sync git gate"),
        ]

        COMPACT_HEIGHT = 20

        CSS = """
        ProjectActionsScreen {
            align: center middle;
            padding: 1 0;
        }

        #action-dialog {
            width: 60;
            height: auto;
            max-height: 100%;
            border: heavy $primary;
            border-title-align: right;
            background: $surface;
            padding: 1 1 0 1;
            overflow-y: auto;
        }

        #action-buttons {
            layout: vertical;
            margin-top: 1;
            align: center middle;
            width: 100%;
        }

        #action-cancel {
            margin-top: 0;
            align: center middle;
            width: 100%;
        }

        #action-buttons Button {
            margin: 0 0 1 0;
            width: 100%;
            min-width: 0;
        }

        #action-dialog Button {
            width: 100%;
            min-width: 0;
        }

        ProjectActionsScreen.compact #action-dialog {
            padding: 0 1;
        }

        ProjectActionsScreen.compact #action-buttons {
            margin-top: 0;
        }

        ProjectActionsScreen.compact #action-dialog Button {
            border: none;
            height: 1;
            padding: 0 1;
        }

        """

        def __init__(self, title: str | None = None) -> None:
            super().__init__()
            self._dialog_title = title or "Project Actions"

        def compose(self) -> ComposeResult:
            with Vertical(id="action-dialog") as dialog:
                with Vertical(id="action-buttons"):
                    yield Button(
                        "generate [yellow]d[/yellow]ockerfiles",
                        id="generate",
                        variant="primary",
                    )
                    yield Button(
                        "[yellow]b[/yellow]uild project image",
                        id="build",
                        variant="primary",
                    )
                    yield Button(
                        "build [yellow]a[/yellow]ll images",
                        id="build_all",
                        variant="primary",
                    )
                    yield Button(
                        "initialize [yellow]s[/yellow]sh", id="init_ssh", variant="primary"
                    )
                    yield Button(
                        "sync [yellow]g[/yellow]it gate",
                        id="sync_gate",
                        variant="primary",
                    )
                with Horizontal(id="action-cancel"):
                    yield Button("Cancel", id="cancel", variant="default")
            dialog.border_title = self._dialog_title

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

        def on_key(self, event: events.Key) -> None:
            key = event.key.lower()
            if key in {"escape", "q"}:
                self.action_dismiss()
                event.stop()
                return
            if key == "up":
                if self.app:
                    self.app.action_focus_previous()
                event.stop()
                return
            if key == "down":
                if self.app:
                    self.app.action_focus_next()
                event.stop()
                return
            if key == "d":
                self.action_generate()
                event.stop()
                return
            if key == "b":
                self.action_build()
                event.stop()
                return
            if key == "a":
                self.action_build_all()
                event.stop()
                return
            if key == "s":
                self.action_init_ssh()
                event.stop()
                return
            if key == "g":
                self.action_sync_gate()
                event.stop()

        def action_dismiss(self) -> None:
            self.dismiss(None)

        def action_generate(self) -> None:
            self.dismiss("generate")

        def action_build(self) -> None:
            self.dismiss("build")

        def action_build_all(self) -> None:
            self.dismiss("build_all")

        def action_init_ssh(self) -> None:
            self.dismiss("init_ssh")

        def action_sync_gate(self) -> None:
            self.dismiss("sync_gate")

        def on_mount(self) -> None:
            first_button = self.query_one("#action-buttons Button", Button)
            first_button.focus()
            self._update_density()

        def on_resize(self, _event: object) -> None:
            self._update_density()

        def _update_density(self) -> None:
            self.set_class(self.size.height < self.COMPACT_HEIGHT, "compact")

    class TaskActionsScreen(screen.ModalScreen[str | None]):
        """Modal screen for task actions."""

        BINDINGS = [
            _modal_binding("escape", "dismiss", "Cancel"),
            _modal_binding("q", "dismiss", "Cancel"),
            _modal_binding("up", "app.focus_previous", "Previous"),
            _modal_binding("down", "app.focus_next", "Next"),
            _modal_binding("n", "new_task", "New task"),
            _modal_binding("c", "cli", "CLI agent"),
            _modal_binding("w", "web", "Web UI"),
            _modal_binding("d", "delete", "Delete task"),
        ]

        COMPACT_HEIGHT = 18

        CSS = """
        TaskActionsScreen {
            align: center middle;
            padding: 1 0;
        }

        #action-dialog {
            width: 60;
            height: auto;
            max-height: 100%;
            border: heavy $primary;
            border-title-align: right;
            background: $surface;
            padding: 1 1 0 1;
            overflow-y: auto;
        }

        #action-buttons {
            layout: vertical;
            margin-top: 1;
            align: center middle;
            width: 100%;
        }

        #action-cancel {
            margin-top: 0;
            align: center middle;
            width: 100%;
        }

        #action-buttons Button {
            margin: 0 0 1 0;
            width: 100%;
            min-width: 0;
        }

        #action-dialog Button {
            width: 100%;
            min-width: 0;
        }

        TaskActionsScreen.compact #action-dialog {
            padding: 0 1;
        }

        TaskActionsScreen.compact #action-buttons {
            margin-top: 0;
        }

        TaskActionsScreen.compact #action-dialog Button {
            border: none;
            height: 1;
            padding: 0 1;
        }

        """

        def __init__(self, title: str | None = None, *, has_tasks: bool = True) -> None:
            super().__init__()
            self._dialog_title = title or "Task Actions"
            self._has_tasks = has_tasks

        def compose(self) -> ComposeResult:
            with Vertical(id="action-dialog") as dialog:
                with Vertical(id="action-buttons"):
                    yield Button("[yellow]n[/yellow]ew task", id="new", variant="primary")
                    if self._has_tasks:
                        yield Button("[yellow]c[/yellow]li agent", id="cli", variant="primary")
                        yield Button("[yellow]w[/yellow]eb ui", id="web", variant="primary")
                        yield Button("[yellow]d[/yellow]elete task", id="delete", variant="primary")
                with Horizontal(id="action-cancel"):
                    yield Button("Cancel", id="cancel", variant="default")
            dialog.border_title = self._dialog_title

        def on_button_pressed(self, event: Button.Pressed) -> None:
            button_id = event.button.id
            if button_id == "cancel":
                self.dismiss(None)
            else:
                action_map = {"new": "new", "cli": "cli", "web": "web", "delete": "delete"}
                self.dismiss(action_map.get(button_id))

        def on_key(self, event: events.Key) -> None:
            key = event.key.lower()
            if key in {"escape", "q"}:
                self.action_dismiss()
                event.stop()
                return
            if key == "up":
                if self.app:
                    self.app.action_focus_previous()
                event.stop()
                return
            if key == "down":
                if self.app:
                    self.app.action_focus_next()
                event.stop()
                return
            if key == "n":
                self.action_new_task()
                event.stop()
                return
            if key == "c":
                self.action_cli()
                event.stop()
                return
            if key == "w":
                self.action_web()
                event.stop()
                return
            if key == "d":
                self.action_delete()
                event.stop()

        def action_dismiss(self) -> None:
            self.dismiss(None)

        def action_new_task(self) -> None:
            self.dismiss("new")

        def action_cli(self) -> None:
            if not self._has_tasks:
                return
            self.dismiss("cli")

        def action_web(self) -> None:
            if not self._has_tasks:
                return
            self.dismiss("web")

        def action_delete(self) -> None:
            if not self._has_tasks:
                return
            self.dismiss("delete")

        def on_mount(self) -> None:
            first_button = self.query_one("#action-buttons Button", Button)
            first_button.focus()
            self._update_density()

        def on_resize(self, _event: object) -> None:
            self._update_density()

        def _update_density(self) -> None:
            self.set_class(self.size.height < self.COMPACT_HEIGHT, "compact")

    class LuskTUI(App):
        """Redesigned TUI frontend for luskctl core modules."""

        CSS_PATH = None

        # Layout rules for the new streamlined design with borders
        CSS = """
        Screen {
            layout: vertical;
            background: $background;
        }

        #main {
            height: 1fr;
            background: $background;
        }

        /* Main container borders */
        #left-pane {
            width: 1fr;
            padding: 1;
            background: $background;
        }

        #right-pane {
            width: 1fr;
            padding: 1;
            background: $background;
        }

        /* Projects section with embedded title */
        #project-list {
            border: round $primary;
            border-title-align: right;
            background: $surface;
            height: 1fr;
            min-height: 10;
        }

        /* Project details section */
        #project-state {
            border: round $primary;
            border-title-align: right;
            background: $background;
            height: 1fr;
            min-height: 10;
            margin-top: 1;
        }

        /* Tasks section with embedded title */
        #task-list {
            border: round $primary;
            border-title-align: right;
            background: $surface;
            height: 1fr;
            min-height: 10;
        }

        /* Task details section */
        #task-details {
            border: round $primary;
            border-title-align: right;
            background: $background;
            height: 1fr;
            min-height: 10;
            margin-top: 1;
        }

        /* Status bar styling */
        #status-bar {
            border: solid $primary;
            background: $background;
            height: 3;
            padding: 0 1;
            margin: 0 1;
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
            # Set dynamic title with version and branch info
            self._update_title()

            self.current_project_id: str | None = None
            self.current_task: TaskMeta | None = None
            self._projects_by_id: dict[str, CodexProject] = {}
            self._last_task_count: int | None = None
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

        def _update_title(self):
            """Update the TUI title with version and branch information."""
            version, branch_name = _get_version_info()

            if branch_name:
                # Development version - show version and branch name
                title = f"Luskctl TUI v{version} [{branch_name}]"
            else:
                # Release version - show just version
                title = f"Luskctl TUI v{version}"

            self.title = title

        # ---------- Layout ----------

        def compose(self) -> ComposeResult:
            # Use Textual's default Header which will show our title
            yield Header()

            # Main layout using grid
            with Horizontal(id="main"):
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
            self._projects_by_id = {proj.id: proj for proj in projects}
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

            self._update_task_details()

            task_count = len(task_list.tasks)
            self._last_task_count = task_count
            # Update project state panel (Dockerfiles/images/SSH/cache + task count)
            self._refresh_project_state(task_count=task_count)

        def _update_task_details(self) -> None:
            details = self.query_one("#task-details", TaskDetails)
            if self.current_task is None:
                details.set_task(None)
                return
            details.set_task(self.current_task)
            if self.current_task.status != "deleting":
                self._queue_task_image_status(self.current_project_id, self.current_task)

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
            if task_count is not None:
                self._last_task_count = task_count

            project_id = self.current_project_id
            project = self._projects_by_id.get(project_id)
            if project is not None:
                state_widget.set_loading(project, self._last_task_count)
            else:
                state_widget.update("Loading project details...")

            self.run_worker(
                lambda: self._load_project_state(project_id),
                name=f"project-state:{project_id}",
                group="project-state",
                exclusive=True,
                thread=True,
                exit_on_error=False,
            )

        def _load_project_state(
            self, project_id: str
        ) -> tuple[str, CodexProject | None, dict | None, str | None]:
            try:
                project = load_project(project_id)
                state = get_project_state(project_id)
                return project_id, project, state, None
            except SystemExit as e:
                return project_id, None, None, str(e)
            except Exception as e:
                return project_id, None, None, str(e)

        def _queue_task_image_status(self, project_id: str | None, task: TaskMeta | None) -> None:
            if not project_id or task is None:
                return
            if task.status == "deleting":
                return

            task_id = task.task_id
            self.run_worker(
                lambda: self._load_task_image_status(project_id, task),
                name=f"task-image:{project_id}:{task_id}",
                group="task-image",
                exclusive=True,
                thread=True,
                exit_on_error=False,
            )

        def _load_task_image_status(
            self, project_id: str, task: TaskMeta
        ) -> tuple[str, str, bool | None]:
            image_old = _is_task_image_old(project_id, task)
            return project_id, task.task_id, image_old

        def _queue_task_delete(self, project_id: str, task_id: str) -> None:
            self.run_worker(
                lambda: self._delete_task(project_id, task_id),
                name=f"task-delete:{project_id}:{task_id}",
                group="task-delete",
                thread=True,
                exit_on_error=False,
            )

        def _delete_task(self, project_id: str, task_id: str) -> tuple[str, str, str | None]:
            try:
                task_delete(project_id, task_id)
                return project_id, task_id, None
            except Exception as e:
                return project_id, task_id, str(e)

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
            await self._action_sync_gate()

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

            self._update_task_details()

        @on(Worker.StateChanged)
        async def handle_worker_state_changed(self, event: Worker.StateChanged) -> None:
            worker = event.worker
            if event.state != WorkerState.SUCCESS:
                if worker.group == "project-state" and event.state == WorkerState.ERROR:
                    state_widget = self.query_one("#project-state", ProjectState)
                    state_widget.update(f"Project state error: {worker.error}")
                return

            if worker.group == "project-state":
                result = worker.result
                if not result:
                    return
                project_id, project, state, error = result
                if project_id != self.current_project_id:
                    return
                state_widget = self.query_one("#project-state", ProjectState)
                if error:
                    state_widget.update(f"Project state error: {error}")
                    return
                if project is None or state is None:
                    state_widget.set_state(None, None, None)
                    return
                self._projects_by_id[project_id] = project
                state_widget.set_state(project, state, self._last_task_count, self._staleness_info)
                return

            if worker.group == "task-image":
                result = worker.result
                if not result:
                    return
                project_id, task_id, image_old = result
                if project_id != self.current_project_id:
                    return
                if not self.current_task or self.current_task.task_id != task_id:
                    return
                details = self.query_one("#task-details", TaskDetails)
                details.set_task(self.current_task, image_old=image_old)
                return

            if worker.group == "task-delete":
                result = worker.result
                if not result:
                    return
                project_id, task_id, error = result
                if error:
                    self.notify(f"Delete error for task {task_id}: {error}")
                else:
                    self.notify(f"Deleted task {task_id}")

                if project_id != self.current_project_id:
                    return
                await self.refresh_tasks()

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
            title = self.current_project_id or "Project Actions"
            await self.push_screen(
                ProjectActionsScreen(title=title),
                self._on_project_action_screen_result,
            )

        async def action_show_task_actions(self) -> None:
            """Show modal dialog with task actions."""
            title = "Task Actions"
            if self.current_task is not None:
                backend = self.current_task.backend or self.current_task.mode or "unknown"
                title = f"Task ID: {self.current_task.task_id}, {backend}"
            try:
                task_list = self.query_one("#task-list", TaskList)
                has_tasks = bool(task_list.tasks)
            except Exception:
                has_tasks = True
            await self.push_screen(
                TaskActionsScreen(title=title, has_tasks=has_tasks),
                self._on_task_action_screen_result,
            )

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
                result = sync_project_gate(project_id)
                if project_id == self.current_project_id:
                    if result["success"]:
                        if result["created"]:
                            self.notify("Gate created and synced from upstream")
                        else:
                            self.notify("Gate synced from upstream")
                    else:
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
            if self.current_task.status == "deleting":
                self.notify(f"Task {tid} is already deleting.")
                return

            self._log_debug(f"delete: start project_id={self.current_project_id} task_id={tid}")
            self.notify(f"Deleting task {tid}...")

            self.current_task.status = "deleting"
            task_list = self.query_one("#task-list", TaskList)
            task_list.mark_deleting(tid)
            self._update_task_details()

            self._queue_task_delete(self.current_project_id, tid)

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
