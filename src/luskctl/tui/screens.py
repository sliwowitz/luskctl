#!/usr/bin/env python3

from textual import events, screen
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button

try:  # pragma: no cover - optional import for test stubs
    from textual.binding import Binding
except Exception:  # pragma: no cover - textual may be a stub module
    Binding = None  # type: ignore[assignment]


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
        _modal_binding("a", "build_agents", "Rebuild with fresh agents"),
        _modal_binding("f", "build_full", "Full rebuild no cache"),
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
                    "rebuild with [yellow]a[/yellow]gents",
                    id="build_agents",
                    variant="primary",
                )
                yield Button(
                    "[yellow]f[/yellow]ull rebuild no cache",
                    id="build_full",
                    variant="primary",
                )
                yield Button("initialize [yellow]s[/yellow]sh", id="init_ssh", variant="primary")
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
                "build_agents": "build_agents",
                "build_full": "build_full",
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
            self.action_build_agents()
            event.stop()
            return
        if key == "f":
            self.action_build_full()
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

    def action_build_agents(self) -> None:
        self.dismiss("build_agents")

    def action_build_full(self) -> None:
        self.dismiss("build_full")

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
