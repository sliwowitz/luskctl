#!/usr/bin/env python3

import inspect
from dataclasses import dataclass
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, ListItem, ListView, Static

from ..lib.git_gate import GateStalenessInfo
from ..lib.projects import Project as CodexProject


@dataclass
class TaskMeta:
    task_id: str
    status: str
    mode: str | None
    workspace: str
    web_port: int | None
    backend: str | None = None


def get_backend_name(task: TaskMeta) -> str | None:
    """Get the backend name for a task.

    Returns the backend name from the task's backend field, or None if not set.
    """
    return task.backend


def get_backend_emoji(task: TaskMeta) -> str:
    """Get the emoji for a task's backend.

    Returns the appropriate emoji based on the task's backend field.
    """
    backend = get_backend_name(task)

    # Return emoji based on backend
    emoji_map = {
        "mistral": "🏰",  # Castle emoji for Mistral
        "claude": "✴️",  # Eight-point star emoji for Claude
        "codex": "🕸️",  # Spider web emoji for Codex
    }
    return emoji_map.get(backend, "🦗")  # Cricket emoji for unknown


class ProjectList(ListView):
    """Left-hand project list widget."""

    class ProjectSelected(Message):
        def __init__(self, project_id: str) -> None:
            super().__init__()
            self.project_id = project_id

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.projects: list[CodexProject] = []

    def set_projects(self, projects: list[CodexProject]) -> None:
        """Populate the list with projects."""
        self.projects = projects
        self.clear()
        for proj in projects:
            # Use emojis instead of text labels
            if proj.security_class == "gatekeeping":
                security_emoji = "🚪"  # Door emoji for gatekeeping
            else:
                security_emoji = "🌐"  # Globe emoji for online
            label = f"{security_emoji} {proj.id}"
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
        self._post_selected_project()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:  # type: ignore[override]
        """Update selection immediately when highlight changes."""
        if event.item is None:
            return
        self._post_selected_project()

    def _post_selected_project(self) -> None:
        idx = self.index
        if 0 <= idx < len(self.projects):
            proj_id = self.projects[idx].id
            self.post_message(self.ProjectSelected(proj_id))


class ProjectActions(Static):
    """Single-row action bar for project + task actions."""

    def compose(self) -> ComposeResult:
        # Short labels so they comfortably fit in 80 columns.  We arrange
        # the buttons in two horizontal rows so they don't form a single
        # over-wide line in the right-hand pane on narrower terminals.
        #
        # Textual 0.6.x doesn't support Horizontal(wrap=...), so we use
        # two Horizontal containers stacked vertically instead of relying
        # on automatic wrapping.

        # First row of actions (project-level).
        #
        # Textual buttons support markup in their labels, so we use markup
        # to highlight the shortcut character instead of literal square
        # brackets (which are reserved for markup tags).
        with Horizontal():
            # Color the shortcut letter yellow; the rest uses the button's
            # normal style (which is already bold by default in Textual's
            # theme). Avoid additional [bold] tags so only the color
            # distinguishes the shortcut.
            yield Button(
                "[yellow]g[/yellow]en", id="btn-generate", compact=True
            )  # generate Dockerfiles (g)
            yield Button("[yellow]b[/yellow]uild", id="btn-build", compact=True)  # build images (b)
            yield Button(
                "[yellow]s[/yellow]sh", id="btn-ssh-init", compact=True
            )  # init SSH dir (s)
            yield Button(
                "[yellow]S[/yellow]ync", id="btn-sync-gate", compact=True
            )  # sync gate from upstream (S)

        # Second row of actions (task-level).
        with Horizontal():
            yield Button("[yellow]t[/yellow] new", id="btn-new-task", compact=True)  # new task (t)
            yield Button(
                "[yellow]r[/yellow] cli", id="btn-task-run-cli", compact=True
            )  # run CLI for current task (r)
            yield Button(
                "[yellow]w[/yellow] web", id="btn-task-run-web", compact=True
            )  # run web for current task (w)
            yield Button(
                "[yellow]d[/yellow]el", id="btn-task-delete", compact=True
            )  # delete current task (d)

    async def on_button_pressed(self, event: Button.Pressed) -> None:  # type: ignore[override]
        btn_id = event.button.id
        app = self.app
        if not app or not btn_id:
            return

        # Call methods on the App if they exist
        mapping = {
            "btn-generate": "action_generate_dockerfiles",
            "btn-build": "action_build_images",
            "btn-ssh-init": "action_init_ssh",
            "btn-sync-gate": "action_sync_gate",
            "btn-new-task": "action_new_task",
            "btn-task-run-cli": "action_run_cli",
            "btn-task-run-web": "action_run_web",
            "btn-task-delete": "action_delete_task",
        }
        method_name = mapping.get(btn_id)
        if not method_name or not hasattr(app, method_name):
            return

        method = getattr(app, method_name)
        result = method()  # type: ignore[misc]
        if inspect.isawaitable(result):
            await result


class TaskList(ListView):
    """Middle pane: per-project tasks."""

    class TaskSelected(Message):
        def __init__(self, project_id: str, task: TaskMeta) -> None:
            super().__init__()
            self.project_id = project_id
            self.task = task

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.project_id: str | None = None
        self.tasks: list[TaskMeta] = []

    def set_tasks(self, project_id: str, tasks_meta: list[dict[str, Any]]) -> None:
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
                web_port=meta.get("web_port"),
                backend=meta.get("backend"),
            )
            self.tasks.append(tm)

            # Use emojis for task types and update status display
            task_emoji = ""
            if tm.mode == "cli":
                task_emoji = "⌨️"  # Keyboard emoji for CLI
            elif tm.mode == "web":
                # Use backend-specific emojis for web tasks
                task_emoji = get_backend_emoji(tm)

            # Update status display to be more consistent
            status_display = tm.status
            extra_parts = []

            # For running tasks, show "running" consistently
            if tm.status == "created" and tm.web_port:
                status_display = "running"
                extra_parts.append(f"port={tm.web_port}")
            elif tm.status == "created" and tm.mode == "cli":
                status_display = "running"

            extra_str = "; ".join(extra_parts)

            # This string has [...] and "mode=..." so we MUST disable markup.
            status_gap = " "
            if status_display == "created":
                status_gap = "   "
            elif status_display == "running":
                status_gap = "  "
            label = f"{tm.task_id} {task_emoji}{status_gap}[{status_display}"
            if extra_str:
                label += f"; {extra_str}"
            label += "]"

            self.append(ListItem(Static(label, markup=False)))

    def get_selected_task(self) -> TaskMeta | None:
        idx = self.index
        if 0 <= idx < len(self.tasks):
            return self.tasks[idx]
        return None

    def on_list_view_selected(self, event: ListView.Selected) -> None:  # type: ignore[override]
        """When user selects a task row, send a semantic TaskSelected message."""
        self._post_selected_task()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:  # type: ignore[override]
        """Update selection immediately when highlight changes."""
        if event.item is None:
            return
        self._post_selected_task()

    def _post_selected_task(self) -> None:
        if self.project_id is None:
            return
        task = self.get_selected_task()
        if task is not None:
            self.post_message(self.TaskSelected(self.project_id, task))


class TaskDetails(Static):
    """Panel showing details for the currently selected task."""

    class CopyDiffRequested(Message):
        """Message sent when user requests to copy git diff."""

        def __init__(self, project_id: str, task_id: str, diff_type: str) -> None:
            super().__init__()
            self.project_id = project_id
            self.task_id = task_id
            self.diff_type = diff_type  # "HEAD" or "PREV"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.current_project_id: str | None = None
        self.current_task_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="task-details-content")
        with Horizontal(id="task-details-actions"):
            yield Button("Copy Diff vs HEAD", id="btn-copy-diff-head", variant="primary")
            yield Button("Copy Diff vs PREV", id="btn-copy-diff-prev", variant="primary")

    def set_task(self, task: TaskMeta | None) -> None:
        content = self.query_one("#task-details-content", Static)

        if task is None:
            content.update("No task selected.")
            self.current_project_id = None
            self.current_task_id = None
            return

        # Store current task info for button handlers
        self.current_project_id = self.app.current_project_id if self.app else None
        self.current_task_id = task.task_id

        # Use emojis for task types
        task_emoji = ""
        mode_display = task.mode or "unset"
        if task.mode == "cli":
            task_emoji = "⌨️ "  # Keyboard emoji for CLI
            mode_display = "CLI"
        elif task.mode == "web":
            # Use backend-specific emojis for web tasks
            emoji = get_backend_emoji(task)
            task_emoji = f"{emoji} "

            # Get backend for display name
            backend = get_backend_name(task)

            # Capitalize backend name for display
            if backend:
                backend_display = backend.capitalize()
            else:
                backend_display = "Unknown"
            mode_display = f"Web UI ({backend_display})"

        # Update status display
        status_display = task.status
        if task.status == "created" and (task.web_port or task.mode == "cli"):
            status_display = "running"

        lines = [
            f"Task ID:   {task.task_id}",
            f"Status:    {status_display}",
            f"Type:      {task_emoji}{mode_display}",
            f"Workspace: {task.workspace}",
        ]
        if task.web_port:
            lines.append(f"Web URL:   http://127.0.0.1:{task.web_port}/")

        content.update("\n".join(lines))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses for copy diff actions."""
        if not self.current_project_id or not self.current_task_id:
            return

        btn_id = event.button.id
        diff_type = "HEAD" if btn_id == "btn-copy-diff-head" else "PREV"

        self.post_message(
            self.CopyDiffRequested(self.current_project_id, self.current_task_id, diff_type)
        )


class ProjectState(Static):
    """Panel showing detailed information about the active project."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def set_state(
        self,
        project: CodexProject | None,
        state: dict | None,
        task_count: int | None = None,
        staleness: GateStalenessInfo | None = None,
    ) -> None:
        if project is None or state is None:
            self.update("No project selected.")
            return

        def _status(value: str) -> str:
            if value == "yes":
                return "[green]yes[/green]"
            if value == "old":
                return "[yellow3]old[/yellow3]"
            return "[red]no[/red]"

        docker_s = _status("yes" if state.get("dockerfiles") else "no")
        images_s = _status("yes" if state.get("images") else "no")
        ssh_s = _status("yes" if state.get("ssh") else "no")
        gate_value = "yes" if state.get("gate") else "no"
        if (
            gate_value == "yes"
            and staleness is not None
            and not staleness.error
            and staleness.is_stale
        ):
            gate_value = "old"
        gate_s = _status(gate_value)

        if task_count is None:
            tasks_line = "Tasks:     unknown"
        else:
            tasks_line = f"Tasks:     {task_count}"

        upstream = project.upstream_url or "-"

        # Use emojis for security class
        if project.security_class == "gatekeeping":
            security_emoji = "🚪"  # Door emoji for gatekeeping
        else:
            security_emoji = "🌐"  # Globe emoji for online

        lines = [
            f"Project:   {project.id} {security_emoji}",
            upstream,
            "",
            f"Dockerfiles: {docker_s}",
            f"Images:      {images_s}",
            f"SSH dir:     {ssh_s}",
            f"Git gate:    {gate_s}",
            tasks_line,
        ]

        # Add gate commit info if available
        gate_commit = state.get("gate_last_commit")
        if gate_commit:
            lines.append("")
            lines.append("Gate info:")
            lines.append(f"  Commit:   {gate_commit.get('commit_hash', 'unknown')[:8]}")
            lines.append(f"  Date:     {gate_commit.get('commit_date', 'unknown')}")
            lines.append(f"  Author:   {gate_commit.get('commit_author', 'unknown')}")
            lines.append(
                f"  Message:  {gate_commit.get('commit_message', 'unknown')[:50]}{'...' if len(gate_commit.get('commit_message', '')) > 50 else ''}"
            )

        # Add upstream staleness info if available (gatekeeping projects only)
        if staleness is not None:
            lines.append("")
            lines.append("Upstream status:")
            if staleness.error:
                lines.append(f"  Error:    {staleness.error}")
            elif staleness.is_stale:
                behind_str = "unknown"
                if staleness.commits_behind is not None:
                    behind_str = str(staleness.commits_behind)
                lines.append(f"  Status:   BEHIND ({behind_str} commits) on {staleness.branch}")
                lines.append(
                    f"  Upstream: {staleness.upstream_head[:8] if staleness.upstream_head else 'unknown'}"
                )
                lines.append(
                    f"  Gate:     {staleness.gate_head[:8] if staleness.gate_head else 'unknown'}"
                )
            else:
                lines.append(f"  Status:   Up to date on {staleness.branch}")
                lines.append(
                    f"  Commit:   {staleness.gate_head[:8] if staleness.gate_head else 'unknown'}"
                )
            lines.append(f"  Checked:  {staleness.last_checked}")

        self.update("\n".join(lines))


class StatusBar(Static):
    """Bottom status bar showing minimal key hints plus status text.

    This replaces Textual's default Footer so we can free horizontal space
    for real status messages instead of a long list of shortcuts. The
    shortcut hints are kept very small here because the primary shortcut
    hints already live in the ProjectActions button bar.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Initialize with an empty message; the App will populate this.
        self.message: str = ""
        self._update_content()

    def set_message(self, message: str) -> None:
        """Update the status message area.

        The left side of the bar is reserved for a couple of always-on
        shortcut hints ("q Quit" and "^P Palette"); the rest of the line is
        dedicated to this message text.
        """

        self.message = message
        self._update_content()

    def _update_content(self) -> None:
        self.update(self.message or "")
