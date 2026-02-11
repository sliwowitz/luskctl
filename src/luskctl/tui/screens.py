#!/usr/bin/env python3

from textual import events, screen
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Static

try:  # pragma: no cover - optional import for test stubs
    from textual.binding import Binding
except Exception:  # pragma: no cover - textual may be a stub module
    Binding = None  # type: ignore[assignment]

from ..lib.git_gate import GateStalenessInfo
from ..lib.projects import Project as CodexProject
from .widgets import TaskMeta, render_project_details, render_task_details


def _modal_binding(key: str, action: str, description: str) -> tuple | object:
    if Binding is None:
        return (key, action, description)
    return Binding(key, action, description, show=False)


# ---------------------------------------------------------------------------
# Shared CSS for full-page detail screens
# ---------------------------------------------------------------------------

_DETAIL_SCREEN_CSS = """
    #detail-content {
        height: auto;
        max-height: 50%;
        border: round $primary;
        border-title-align: right;
        background: $surface;
        padding: 1;
        margin: 1;
        overflow-y: auto;
    }

    #actions-container {
        height: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }

    .action-group-label {
        margin: 1 0 0 1;
        text-style: bold;
        color: $text-muted;
    }

    .action-group {
        layout: vertical;
        margin: 0 1;
        height: auto;
    }

    .action-group Button {
        margin: 0 0 1 0;
        width: 100%;
        min-width: 0;
    }

    #action-cancel {
        margin: 0 1 1 1;
        height: auto;
    }

    #action-cancel Button {
        width: 100%;
        min-width: 0;
    }
"""


# ---------------------------------------------------------------------------
# Project Details Screen
# ---------------------------------------------------------------------------


class ProjectDetailsScreen(screen.Screen[str | None]):
    """Full-page detail screen for a project with categorized actions."""

    BINDINGS = [
        _modal_binding("escape", "dismiss", "Back"),
        _modal_binding("q", "dismiss", "Back"),
        _modal_binding("i", "project_init", "Full Setup"),
        _modal_binding("g", "sync_gate", "Sync git gate"),
        _modal_binding("d", "generate", "Generate dockerfiles"),
        _modal_binding("b", "build", "Build project image"),
        _modal_binding("r", "build_agents", "Rebuild with agents"),
        _modal_binding("f", "build_full", "Full rebuild no cache"),
        _modal_binding("s", "init_ssh", "Init SSH"),
        _modal_binding("a", "auth", "Authenticate agents"),
    ]

    CSS = (
        """
    ProjectDetailsScreen {
        layout: vertical;
        background: $background;
    }
    """
        + _DETAIL_SCREEN_CSS
    )

    def __init__(
        self,
        project: CodexProject,
        state: dict | None,
        task_count: int | None,
        staleness: GateStalenessInfo | None = None,
    ) -> None:
        super().__init__()
        self._project = project
        self._state = state
        self._task_count = task_count
        self._staleness = staleness

    def compose(self) -> ComposeResult:
        detail_pane = Static(id="detail-content")
        detail_pane.border_title = f"Project: {self._project.id}"
        yield detail_pane

        with VerticalScroll(id="actions-container"):
            yield Static("Common Actions", classes="action-group-label")
            with Vertical(classes="action-group"):
                yield Button(
                    "Full Setup - project-[yellow]i[/yellow]nit"
                    "  (ssh + generate + build + gate-sync)",
                    id="project_init",
                    variant="primary",
                )
                yield Button(
                    "sync [yellow]g[/yellow]it gate",
                    id="sync_gate",
                    variant="primary",
                )

            yield Static("Build & Configure", classes="action-group-label")
            with Vertical(classes="action-group"):
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
                    "[yellow]r[/yellow]ebuild with agents",
                    id="build_agents",
                    variant="primary",
                )
                yield Button(
                    "[yellow]f[/yellow]ull rebuild no cache",
                    id="build_full",
                    variant="primary",
                )
                yield Button(
                    "initialize [yellow]s[/yellow]sh",
                    id="init_ssh",
                    variant="primary",
                )

            yield Static("Authentication", classes="action-group-label")
            with Vertical(classes="action-group"):
                yield Button(
                    "[yellow]a[/yellow]uthenticate agents...",
                    id="auth",
                    variant="primary",
                )

        with Horizontal(id="action-cancel"):
            yield Button("Cancel [Esc]", id="cancel", variant="default")

    def on_mount(self) -> None:
        detail_widget = self.query_one("#detail-content", Static)
        rendered = render_project_details(
            self._project, self._state, self._task_count, self._staleness
        )
        detail_widget.update(rendered)
        first_button = self.query("Button").first()
        if first_button:
            first_button.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "cancel":
            self.dismiss(None)
        elif button_id == "auth":
            self._open_auth_modal()
        elif button_id:
            self.dismiss(button_id)

    def _open_auth_modal(self) -> None:
        self.app.push_screen(AuthActionsScreen(), self._on_auth_result)

    def _on_auth_result(self, result: str | None) -> None:
        if result:
            self.dismiss(result)

    # Action methods invoked by BINDINGS
    def action_dismiss(self) -> None:
        self.dismiss(None)

    def action_project_init(self) -> None:
        self.dismiss("project_init")

    def action_sync_gate(self) -> None:
        self.dismiss("sync_gate")

    def action_generate(self) -> None:
        self.dismiss("generate")

    def action_build(self) -> None:
        self.dismiss("build")

    def action_build_agents(self) -> None:
        self.dismiss("build_agents")

    def action_build_full(self) -> None:
        self.dismiss("build_full")

    def action_init_ssh(self) -> None:
        self.dismiss("init_ssh")

    def action_auth(self) -> None:
        self._open_auth_modal()


# ---------------------------------------------------------------------------
# Auth Actions Modal (sub-modal of ProjectDetailsScreen)
# ---------------------------------------------------------------------------


class AuthActionsScreen(screen.ModalScreen[str | None]):
    """Small modal for selecting which agent to authenticate."""

    BINDINGS = [
        _modal_binding("escape", "dismiss", "Cancel"),
        _modal_binding("q", "dismiss", "Cancel"),
        _modal_binding("1", "auth_codex", "Codex"),
        _modal_binding("2", "auth_claude", "Claude"),
        _modal_binding("3", "auth_mistral", "Mistral"),
        _modal_binding("4", "auth_blablador", "Blablador"),
    ]

    CSS = """
    AuthActionsScreen {
        align: center middle;
    }

    #auth-dialog {
        width: 50;
        height: auto;
        max-height: 80%;
        border: heavy $primary;
        border-title-align: right;
        background: $surface;
        padding: 1;
    }

    #auth-buttons {
        layout: vertical;
        height: auto;
    }

    #auth-buttons Button {
        margin: 0 0 1 0;
        width: 100%;
        min-width: 0;
    }

    #auth-cancel {
        margin-top: 0;
        height: auto;
    }

    #auth-cancel Button {
        width: 100%;
        min-width: 0;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="auth-dialog") as dialog:
            with Vertical(id="auth-buttons"):
                yield Button("[yellow]1[/yellow] Codex", id="auth_codex", variant="primary")
                yield Button("[yellow]2[/yellow] Claude", id="auth_claude", variant="primary")
                yield Button("[yellow]3[/yellow] Mistral", id="auth_mistral", variant="primary")
                yield Button("[yellow]4[/yellow] Blablador", id="auth_blablador", variant="primary")
            with Horizontal(id="auth-cancel"):
                yield Button("Cancel [Esc]", id="cancel", variant="default")
        dialog.border_title = "Authenticate Agents"

    def on_mount(self) -> None:
        first_button = self.query_one("#auth-buttons Button", Button)
        first_button.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "cancel":
            self.dismiss(None)
        elif button_id:
            self.dismiss(button_id)

    # Action methods invoked by BINDINGS
    def action_dismiss(self) -> None:
        self.dismiss(None)

    def action_auth_codex(self) -> None:
        self.dismiss("auth_codex")

    def action_auth_claude(self) -> None:
        self.dismiss("auth_claude")

    def action_auth_mistral(self) -> None:
        self.dismiss("auth_mistral")

    def action_auth_blablador(self) -> None:
        self.dismiss("auth_blablador")


# ---------------------------------------------------------------------------
# Task Details Screen
# ---------------------------------------------------------------------------


class TaskDetailsScreen(screen.Screen[str | None]):
    """Full-page detail screen for a task with categorized actions."""

    # Only escape/q use BINDINGS. Other keys require case-sensitive
    # dispatch (e.g. shift-N vs n) which Textual BINDINGS cannot express,
    # so they are handled in on_key instead.
    BINDINGS = [
        _modal_binding("escape", "dismiss", "Back"),
        _modal_binding("q", "dismiss", "Back"),
    ]

    CSS = (
        """
    TaskDetailsScreen {
        layout: vertical;
        background: $background;
    }
    """
        + _DETAIL_SCREEN_CSS
    )

    def __init__(
        self,
        task: TaskMeta | None,
        has_tasks: bool,
        project_id: str,
        image_old: bool | None = None,
    ) -> None:
        super().__init__()
        self._task = task
        self._has_tasks = has_tasks
        self._project_id = project_id
        self._image_old = image_old

    def compose(self) -> ComposeResult:
        detail_pane = Static(id="detail-content")
        title = "Task Details"
        if self._task:
            backend = self._task.backend or self._task.mode or "unknown"
            title = f"Task: {self._task.task_id} ({backend})"
        detail_pane.border_title = title
        yield detail_pane

        with VerticalScroll(id="actions-container"):
            yield Static("Common Actions", classes="action-group-label")
            with Vertical(classes="action-group"):
                yield Button(
                    "Start CLI task  [yellow]N[/yellow]  (new task + run CLI)",
                    id="task_start_cli",
                    variant="primary",
                )
                yield Button(
                    "Start [yellow]W[/yellow]eb task  (new task + run Web)",
                    id="task_start_web",
                    variant="primary",
                )
                yield Button(
                    "New task (no run)  [yellow]C[/yellow]",
                    id="new",
                    variant="primary",
                )
                if self._has_tasks:
                    yield Button(
                        "[yellow]d[/yellow]elete task",
                        id="delete",
                        variant="error",
                    )

            if self._has_tasks:
                yield Static("Task Operations", classes="action-group-label")
                with Vertical(classes="action-group"):
                    yield Button(
                        "run [yellow]c[/yellow]li agent",
                        id="cli",
                        variant="primary",
                    )
                    yield Button(
                        "run [yellow]w[/yellow]eb UI",
                        id="web",
                        variant="primary",
                    )
                    yield Button(
                        "[yellow]r[/yellow]estart container",
                        id="restart",
                        variant="primary",
                    )

                yield Static("Diff", classes="action-group-label")
                with Vertical(classes="action-group"):
                    yield Button(
                        "Copy diff vs [yellow]H[/yellow]EAD",
                        id="diff_head",
                        variant="primary",
                    )
                    yield Button(
                        "Copy diff vs [yellow]P[/yellow]REV",
                        id="diff_prev",
                        variant="primary",
                    )

        with Horizontal(id="action-cancel"):
            yield Button("Cancel [Esc]", id="cancel", variant="default")

    def on_mount(self) -> None:
        detail_widget = self.query_one("#detail-content", Static)
        rendered = render_task_details(
            self._task,
            project_id=self._project_id,
            image_old=self._image_old,
            empty_message="No task selected.",
        )
        detail_widget.update(rendered)
        first_button = self.query("Button").first()
        if first_button:
            first_button.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "cancel":
            self.dismiss(None)
        elif button_id:
            self.dismiss(button_id)

    def on_key(self, event: events.Key) -> None:
        key = event.key  # case-sensitive

        if key.lower() in ("escape", "q"):
            self.dismiss(None)
            event.stop()
            return

        # Shift keys (uppercase) — N/W/C always available, H/P require tasks
        shift_map = {
            "N": "task_start_cli",
            "W": "task_start_web",
            "C": "new",
            "H": "diff_head",
            "P": "diff_prev",
        }
        if key in shift_map:
            if key in ("H", "P") and not self._has_tasks:
                return
            self.dismiss(shift_map[key])
            event.stop()
            return

        # Lowercase keys — all require tasks to exist
        lower_map = {"d": "delete", "c": "cli", "w": "web", "r": "restart"}
        if key in lower_map:
            if not self._has_tasks:
                return
            self.dismiss(lower_map[key])
            event.stop()

    # Action methods for programmatic access
    def action_dismiss(self) -> None:
        self.dismiss(None)

    def action_task_start_cli(self) -> None:
        self.dismiss("task_start_cli")

    def action_task_start_web(self) -> None:
        self.dismiss("task_start_web")

    def action_new(self) -> None:
        self.dismiss("new")

    def action_delete(self) -> None:
        if self._has_tasks:
            self.dismiss("delete")

    def action_cli(self) -> None:
        if self._has_tasks:
            self.dismiss("cli")

    def action_web(self) -> None:
        if self._has_tasks:
            self.dismiss("web")

    def action_restart(self) -> None:
        if self._has_tasks:
            self.dismiss("restart")

    def action_diff_head(self) -> None:
        if self._has_tasks:
            self.dismiss("diff_head")

    def action_diff_prev(self) -> None:
        if self._has_tasks:
            self.dismiss("diff_prev")
