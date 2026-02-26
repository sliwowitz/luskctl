#!/usr/bin/env python3

from typing import TypedDict

from textual import events, screen
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

try:  # pragma: no cover - optional import for test stubs
    from textual.widgets import OptionList
except Exception:  # pragma: no cover - textual may be a stub module
    OptionList = None  # type: ignore[assignment,misc]

try:  # pragma: no cover - optional import for test stubs
    from textual.widgets.option_list import Option
except Exception:  # pragma: no cover - textual may be a stub module
    Option = None  # type: ignore[assignment,misc]

try:  # pragma: no cover - optional import for test stubs
    from textual.binding import Binding
except Exception:  # pragma: no cover - textual may be a stub module
    Binding = None  # type: ignore[assignment]

try:  # pragma: no cover - optional import for test stubs
    from textual.widgets import TextArea
except Exception:  # pragma: no cover - textual may be a stub module
    TextArea = None  # type: ignore[assignment,misc]

try:  # pragma: no cover - optional import for test stubs
    from textual.widgets import SelectionList
except Exception:  # pragma: no cover - textual may be a stub module
    SelectionList = None  # type: ignore[assignment,misc]

from ..lib.core.projects import Project as CodexProject
from ..lib.facade import GateStalenessInfo
from .widgets import TaskMeta, render_project_details, render_project_loading, render_task_details


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
        border-subtitle-align: left;
        background: $surface;
        padding: 1;
        margin: 1;
        overflow-y: auto;
    }

    #actions-list {
        height: 1fr;
        margin: 0 1;
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
        detail_pane.border_subtitle = "Esc to close"
        yield detail_pane

        yield OptionList(
            Option(
                "Full Setup - project-\\[i]nit  (ssh + generate + build + gate-sync)",
                id="project_init",
            ),
            Option("sync \\[g]it gate", id="sync_gate"),
            None,
            Option("generate \\[d]ockerfiles", id="generate"),
            Option("\\[b]uild project image", id="build"),
            Option("\\[r]ebuild with agents", id="build_agents"),
            Option("\\[f]ull rebuild no cache", id="build_full"),
            Option("initialize \\[s]sh", id="init_ssh"),
            None,
            Option("\\[a]uthenticate agents...", id="auth"),
            id="actions-list",
        )

    def on_mount(self) -> None:
        detail_widget = self.query_one("#detail-content", Static)
        if self._state is not None:
            rendered = render_project_details(
                self._project, self._state, self._task_count, self._staleness
            )
        else:
            rendered = render_project_loading(self._project, self._task_count)
        detail_widget.update(rendered)
        actions = self.query_one("#actions-list", OptionList)
        actions.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id == "auth":
            self._open_auth_modal()
        elif option_id:
            self.dismiss(option_id)

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
    """Small modal for selecting which agent to authenticate.

    Options are built dynamically from ``AUTH_PROVIDERS``.
    Number keys (1-9) act as shortcuts for the corresponding list entry.
    """

    BINDINGS = [
        _modal_binding("escape", "dismiss", "Cancel"),
        _modal_binding("q", "dismiss", "Cancel"),
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
        border-subtitle-align: left;
        background: $surface;
        padding: 1;
    }

    #auth-actions-list {
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        from ..lib.facade import AUTH_PROVIDERS

        options = [
            Option(f"\\[{i}] {p.label}", id=f"auth_{p.name}")
            for i, p in enumerate(AUTH_PROVIDERS.values(), 1)
        ]
        with Vertical(id="auth-dialog") as dialog:
            yield OptionList(*options, id="auth-actions-list")
        dialog.border_title = "Authenticate Agents"
        dialog.border_subtitle = "Esc to close"

    def on_mount(self) -> None:
        actions = self.query_one("#auth-actions-list", OptionList)
        actions.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id:
            self.dismiss(event.option_id)

    def on_key(self, event: events.Key) -> None:
        """Handle number-key shortcuts (1-9) to select a provider."""
        from ..lib.facade import AUTH_PROVIDERS

        if event.character and event.character.isdigit():
            idx = int(event.character) - 1
            providers = list(AUTH_PROVIDERS.values())
            if 0 <= idx < len(providers):
                self.dismiss(f"auth_{providers[idx].name}")
                event.stop()

    def action_dismiss(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Autopilot Prompt Screen
# ---------------------------------------------------------------------------


class AgentInfo(TypedDict):
    """Metadata for a single agent shown in the autopilot selection screen.

    Attributes:
        name: Unique agent identifier used as the dict key in ``--agents`` JSON.
        description: Human-readable summary of the agent's purpose.
        default: Whether the agent is pre-selected when the selection screen opens.
    """

    name: str
    description: str
    default: bool


class AutopilotPromptScreen(screen.ModalScreen[str | None]):
    """Modal for entering an autopilot prompt.

    A modal dialog that prompts the user to enter a prompt for the autopilot
    (headless Claude) mode. The user can enter their prompt in a text area and
    submit it or cancel.

    The screen dismisses with the prompt string if submitted, or ``None``
    if cancelled (e.g. via Escape or the Cancel button).
    """

    BINDINGS = [
        _modal_binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    AutopilotPromptScreen {
        align: center middle;
    }

    #autopilot-dialog {
        width: 80;
        height: auto;
        max-height: 80%;
        border: heavy $primary;
        border-title-align: right;
        border-subtitle-align: left;
        background: $surface;
        padding: 1;
    }

    #prompt-area {
        height: 8;
        margin-bottom: 1;
    }

    #prompt-buttons {
        height: auto;
        align-horizontal: right;
    }

    #prompt-buttons Button {
        margin-left: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="autopilot-dialog") as dialog:
            yield TextArea(id="prompt-area")
            with Horizontal(id="prompt-buttons"):
                yield Button("Cancel", id="btn-cancel", variant="default")
                yield Button("Run ▶", id="btn-run", variant="primary")
        dialog.border_title = "Autopilot Prompt"
        dialog.border_subtitle = "Esc to cancel"

    def on_mount(self) -> None:
        area = self.query_one("#prompt-area", TextArea)
        area.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-run":
            self._submit()
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def _submit(self) -> None:
        area = self.query_one("#prompt-area", TextArea)
        text = area.text.strip()
        if text:
            self.dismiss(text)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Agent Selection Screen
# ---------------------------------------------------------------------------


class AgentSelectionScreen(screen.ModalScreen[list[str] | None]):
    """Modal for selecting non-default agents to include in an autopilot run."""

    BINDINGS = [
        _modal_binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    AgentSelectionScreen {
        align: center middle;
    }

    #agent-dialog {
        width: 60;
        height: auto;
        max-height: 80%;
        border: heavy $primary;
        border-title-align: right;
        border-subtitle-align: left;
        background: $surface;
        padding: 1;
    }

    #agent-selection {
        height: auto;
        max-height: 12;
        margin-bottom: 1;
    }

    #agent-buttons {
        height: auto;
        align-horizontal: right;
    }
    """

    def __init__(self, agents: list[AgentInfo]) -> None:
        """agents: list of AgentInfo dicts with 'name', 'description', 'default' fields."""
        super().__init__()
        self._agents = agents

    def compose(self) -> ComposeResult:
        with Vertical(id="agent-dialog") as dialog:
            items = []
            for agent in self._agents:
                name = agent.get("name", "unnamed")
                desc = agent.get("description", "")
                label = f"{name}: {desc}" if desc else name
                # Pre-select agents marked as default
                initial = bool(agent.get("default", False))
                items.append((label, name, initial))
            yield SelectionList(*items, id="agent-selection")
            with Horizontal(id="agent-buttons"):
                yield Button("Cancel", id="btn-cancel", variant="default")
                yield Button("OK", id="btn-ok", variant="primary")
        dialog.border_title = "Select Agents"
        dialog.border_subtitle = "Esc to cancel"

    def on_mount(self) -> None:
        btn = self.query_one("#btn-ok", Button)
        btn.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-ok":
            self._submit()
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def _submit(self) -> None:
        sel = self.query_one("#agent-selection", SelectionList)
        selected = list(sel.selected)
        self.dismiss(selected)

    def action_cancel(self) -> None:
        self.dismiss(None)


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
        self._task_meta = task
        self._has_tasks = has_tasks
        self._project_id = project_id
        self._image_old = image_old

    def compose(self) -> ComposeResult:
        detail_pane = Static(id="detail-content")
        title = "Task Details"
        if self._task_meta:
            backend = self._task_meta.backend or self._task_meta.mode or "unknown"
            title = f"Task: {self._task_meta.task_id} ({backend})"
        detail_pane.border_title = title
        detail_pane.border_subtitle = "Esc to close"
        yield detail_pane

        options: list[Option | None] = [
            Option("Start CLI task  \\[N]  (new task + run CLI)", id="task_start_cli"),
            Option("Start \\[W]eb task  (new task + run Web)", id="task_start_web"),
            Option(
                "Start \\[A]utopilot task  (new task + run headless)", id="task_start_autopilot"
            ),
        ]
        if self._has_tasks:
            options.append(Option("\\[l]ogin to container", id="login"))
            if self._task_meta and self._task_meta.mode == "run":
                options.append(Option("\\[f]ollow logs", id="follow_logs"))
            options.append(None)
            options.append(Option("run \\[c]li agent", id="cli"))
            options.append(Option("run \\[w]eb UI", id="web"))
            options.append(Option("\\[r]estart container", id="restart"))
            options.append(None)
            options.append(Option("Copy diff vs \\[H]EAD", id="diff_head"))
            options.append(Option("Copy diff vs \\[P]REV", id="diff_prev"))
        options.append(None)
        options.append(Option("New task (no run)  \\[C]", id="new"))

        yield OptionList(*options, id="actions-list")

    def on_mount(self) -> None:
        detail_widget = self.query_one("#detail-content", Static)
        rendered = render_task_details(
            self._task_meta,
            project_id=self._project_id,
            image_old=self._image_old,
            empty_message="No task selected.",
        )
        detail_widget.update(rendered)
        actions = self.query_one("#actions-list", OptionList)
        actions.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if option_id:
            self.dismiss(option_id)

    def on_key(self, event: events.Key) -> None:
        key = event.key  # case-sensitive

        if key.lower() in ("escape", "q"):
            self.dismiss(None)
            event.stop()
            return

        # Shift keys (uppercase) — N/W/A/C always available, H/P require tasks
        shift_map = {
            "N": "task_start_cli",
            "W": "task_start_web",
            "A": "task_start_autopilot",
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
        lower_map = {
            "d": "delete",
            "c": "cli",
            "w": "web",
            "r": "restart",
            "l": "login",
        }
        if key in lower_map:
            if not self._has_tasks:
                return
            self.dismiss(lower_map[key])
            event.stop()
            return

        # 'f' (follow logs) — only available for autopilot tasks
        if key == "f":
            if self._has_tasks and self._task_meta and self._task_meta.mode == "run":
                self.dismiss("follow_logs")
                event.stop()

    def action_dismiss(self) -> None:
        self.dismiss(None)
