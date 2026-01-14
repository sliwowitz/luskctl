#!/usr/bin/env python3

import inspect
import subprocess
from dataclasses import dataclass
from typing import Any

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
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


class ProjectListItem(ListItem):
    """List item that carries project metadata."""

    def __init__(self, project_id: str, label: str, generation: int) -> None:
        super().__init__(Static(label, markup=False))
        self.project_id = project_id
        self.generation = generation


class TaskListItem(ListItem):
    """List item that carries task metadata."""

    def __init__(self, project_id: str, task: TaskMeta, label: str, generation: int) -> None:
        super().__init__(Static(label, markup=False))
        self.project_id = project_id
        self.task_meta = task
        self.generation = generation


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
        "codex": "🌸",  # Blossom emoji for Codex
    }
    return emoji_map.get(backend, "🕸️")  # Spider web emoji for unknown


def draw_emoji(emoji: str, width: int = 2) -> str:
    """Pad emojis to a consistent cell width for list alignment."""
    if not emoji:
        return ""
    try:
        emoji_width = cell_len(emoji)
    except Exception:
        return emoji
    if emoji_width >= width:
        return emoji
    return f"{emoji}{' ' * (width - emoji_width)}"


def _get_css_variables(widget: Static) -> dict[str, str]:
    if widget.app is None:
        return {}
    try:
        return widget.app.get_css_variables()
    except Exception:
        return {}


def _is_task_image_old(project_id: str | None, task: TaskMeta) -> bool | None:
    if project_id is None:
        return None
    if task.mode not in {"cli", "web"}:
        return None

    container_name = f"{project_id}-{task.mode}-{task.task_id}"
    try:
        result = subprocess.run(
            [
                "podman",
                "container",
                "inspect",
                "--format",
                "{{.State.Running}}\t{{.Image}}",
                container_name,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    running_str, _, image_id = result.stdout.partition("\t")
    if running_str.strip().lower() != "true":
        return None
    image_id = image_id.strip()
    if not image_id:
        return None

    try:
        from ..lib.docker import build_context_hash

        current_hash = build_context_hash(project_id)
    except Exception:
        return None

    try:
        label_result = subprocess.run(
            [
                "podman",
                "image",
                "inspect",
                "--format",
                '{{index .Config.Labels "luskctl.build_context_hash"}}',
                image_id,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if label_result.returncode != 0:
        return None

    label = label_result.stdout.strip()
    if not label or label == "<no value>":
        return True
    return label != current_hash


class ProjectList(ListView):
    """Left-hand project list widget."""

    class ProjectSelected(Message):
        def __init__(self, project_id: str) -> None:
            super().__init__()
            self.project_id = project_id

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.projects: list[CodexProject] = []
        self._generation = 0

    def set_projects(self, projects: list[CodexProject]) -> None:
        """Populate the list with projects."""
        self.projects = projects
        self._generation += 1
        self.clear()
        for proj in projects:
            # Use emojis instead of text labels
            if proj.security_class == "gatekeeping":
                security_emoji = "🚪"  # Door emoji for gatekeeping
            else:
                security_emoji = "🌐"  # Globe emoji for online
            emoji_display = draw_emoji(security_emoji)
            label = f"{emoji_display} {proj.id}"
            self.append(ProjectListItem(proj.id, label, self._generation))

    def select_project(self, project_id: str) -> None:
        """Select a project by id."""
        for idx, proj in enumerate(self.projects):
            if proj.id == project_id:
                self.index = idx
                break

    def on_list_view_selected(self, event: ListView.Selected) -> None:  # type: ignore[override]
        """When user selects a row, send a semantic ProjectSelected message."""
        self._post_selected_project(event.item)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:  # type: ignore[override]
        """Update selection immediately when highlight changes."""
        if event.item is None:
            return
        self._post_selected_project(event.item)

    def _post_selected_project(self, item: ListItem | None = None) -> None:
        if item is None:
            item = self.highlighted_child
        if not isinstance(item, ProjectListItem):
            return
        if item.parent is not self:
            return
        if item.generation != self._generation:
            return
        self.post_message(self.ProjectSelected(item.project_id))


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
        self._generation = 0

    def _format_task_label(self, task: TaskMeta) -> str:
        task_emoji = ""
        if task.status == "deleting":
            task_emoji = "🗑️"
        elif task.mode == "cli":
            task_emoji = "⌨️"  # Keyboard emoji for CLI
        elif task.mode == "web":
            task_emoji = get_backend_emoji(task)
        elif task.status == "created":
            task_emoji = "🦗"

        status_display = task.status
        extra_parts: list[str] = []

        if task.status == "created" and task.web_port:
            status_display = "running"
            extra_parts.append(f"port={task.web_port}")
        elif task.status == "created" and task.mode == "cli":
            status_display = "running"

        extra_str = "; ".join(extra_parts)

        emoji_display = draw_emoji(task_emoji)
        label = f"{task.task_id} {emoji_display} [{status_display}"
        if extra_str:
            label += f"; {extra_str}"
        label += "]"
        return label

    def set_tasks(self, project_id: str, tasks_meta: list[dict[str, Any]]) -> None:
        """Populate the list from raw metadata dicts."""
        self.project_id = project_id
        self.tasks = []
        self._generation += 1
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

            label = self._format_task_label(tm)
            self.append(TaskListItem(project_id, tm, label, self._generation))

    def mark_deleting(self, task_id: str) -> bool:
        # Create a new TaskMeta instance with updated status instead of mutating
        # the existing shared instance in place.
        new_meta: TaskMeta | None = None

        # First, update the entry in the internal tasks list if present.
        for index, tm in enumerate(self.tasks):
            if tm.task_id == task_id:
                new_meta = TaskMeta(
                    task_id=tm.task_id,
                    status="deleting",
                    mode=tm.mode,
                    workspace=tm.workspace,
                    web_port=tm.web_port,
                    backend=tm.backend,
                )
                self.tasks[index] = new_meta
                break

        found = False

        # Then, update any visible list items for this task to point at the new
        # TaskMeta instance and refresh their labels.
        for item in self.query(TaskListItem):
            if item.task_meta.task_id != task_id:
                continue

            # If we didn't find the task in self.tasks for some reason, fall back
            # to cloning from the item's TaskMeta.
            if new_meta is None:
                tm = item.task_meta
                new_meta = TaskMeta(
                    task_id=tm.task_id,
                    status="deleting",
                    mode=tm.mode,
                    workspace=tm.workspace,
                    web_port=tm.web_port,
                    backend=tm.backend,
                )

            item.task_meta = new_meta
            label = self._format_task_label(new_meta)
            item.query_one(Static).update(label)
            found = True

        return found

    def on_list_view_selected(self, event: ListView.Selected) -> None:  # type: ignore[override]
        """When user selects a task row, send a semantic TaskSelected message."""
        self._post_selected_task(event.item)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:  # type: ignore[override]
        """Update selection immediately when highlight changes."""
        if event.item is None:
            return
        self._post_selected_task(event.item)

    def _post_selected_task(self, item: ListItem | None = None) -> None:
        if self.project_id is None:
            return
        if item is None:
            item = self.highlighted_child
        if not isinstance(item, TaskListItem):
            return
        if item.parent is not self:
            return
        if item.generation != self._generation:
            return
        if item.project_id != self.project_id:
            return
        self.post_message(self.TaskSelected(self.project_id, item.task_meta))


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

    def set_task(
        self,
        task: TaskMeta | None,
        empty_message: str | None = None,
        image_old: bool | None = None,
    ) -> None:
        content = self.query_one("#task-details-content", Static)

        if task is None:
            content.update(empty_message or "")
            self.current_project_id = None
            self.current_task_id = None
            return

        # Store current task info for button handlers
        self.current_project_id = self.app.current_project_id if self.app else None
        self.current_task_id = task.task_id

        # Use emojis for task types
        task_emoji = ""
        mode_display = task.mode or "unset"
        if task.status == "deleting":
            task_emoji = "🗑️ "
            mode_display = "Deleting"
        elif task.mode == "cli":
            task_emoji = "⌨️ "  # Keyboard emoji for CLI
            mode_display = "CLI"
        elif task.mode == "web":
            # Use backend-specific emojis for web tasks
            emoji = get_backend_emoji(task)
            task_emoji = f"{emoji} "
        elif task.status == "created":
            task_emoji = "🦗 "
            mode_display = "Not assigned (choose CLI or Web mode)"

        # Update status display
        status_display = task.status
        if task.status == "created" and (task.web_port or task.mode == "cli"):
            status_display = "running"

        variables = _get_css_variables(self)
        accent_style = Style(color=variables.get("primary", "cyan"))
        warning_style = Style(color=variables.get("warning", "yellow"))

        lines = [
            Text(f"Task ID:   {task.task_id}"),
            Text(f"Status:    {status_display}"),
            Text(f"Type:      {task_emoji}{mode_display}"),
            Text(f"Workspace: {task.workspace}"),
        ]
        if status_display == "running" and image_old:
            lines.append(
                Text.assemble(
                    "Image:     ",
                    Text("old", style=warning_style),
                )
            )
        if task.web_port:
            lines.append(
                Text.assemble(
                    "Web URL:   ",
                    Text(f"http://127.0.0.1:{task.web_port}/", style=accent_style),
                )
            )
        if task.mode == "cli" and self.current_project_id:
            container_name = f"{self.current_project_id}-cli-{task.task_id}"
            lines.append(
                Text.assemble(
                    "Log in:    ",
                    Text(f"podman exec -it {container_name} bash", style=accent_style),
                )
            )

        content.update(Text("\n").join(lines))

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

    def set_loading(self, project: CodexProject | None, task_count: int | None = None) -> None:
        if project is None:
            self.update(Text("No project selected."))
            return

        upstream = project.upstream_url or "-"

        # Use emojis for security class
        if project.security_class == "gatekeeping":
            security_emoji = "🚪"  # Door emoji for gatekeeping
        else:
            security_emoji = "🌐"  # Globe emoji for online

        if task_count is None:
            tasks_line = Text("Tasks:     loading")
        else:
            tasks_line = Text(f"Tasks:     {task_count}")

        lines = [
            Text(f"Project:   {project.id} {security_emoji}"),
            Text(upstream),
            Text(""),
            Text("Loading details..."),
            tasks_line,
        ]
        self.update(Text("\n").join(lines))

    def set_state(
        self,
        project: CodexProject | None,
        state: dict | None,
        task_count: int | None = None,
        staleness: GateStalenessInfo | None = None,
    ) -> None:
        if project is None or state is None:
            self.update(Text("No project selected."))
            return

        variables = _get_css_variables(self)
        success_color = variables.get("success", "green")
        error_color = variables.get("error", "red")
        warning_color = variables.get("warning", "yellow")

        status_styles = {
            "yes": Style(color=success_color),
            "no": Style(color=error_color),
            "old": Style(color=warning_color),
        }

        def _status_text(value: str) -> Text:
            style = status_styles.get(value, Style(color=error_color))
            return Text(value, style=style)

        docker_value = "yes" if state.get("dockerfiles") else "no"
        if docker_value == "yes" and state.get("dockerfiles_old"):
            docker_value = "old"
        docker_s = _status_text(docker_value)

        images_value = "yes" if state.get("images") else "no"
        if images_value == "yes" and state.get("images_old"):
            images_value = "old"
        images_s = _status_text(images_value)
        ssh_s = _status_text("yes" if state.get("ssh") else "no")
        gate_value = "yes" if state.get("gate") else "no"
        if (
            gate_value == "yes"
            and staleness is not None
            and not staleness.error
            and staleness.is_stale
        ):
            gate_value = "old"
        gate_s = _status_text(gate_value)

        if task_count is None:
            tasks_line = Text("Tasks:     unknown")
        else:
            tasks_line = Text(f"Tasks:     {task_count}")

        upstream = project.upstream_url or "-"

        # Use emojis for security class
        if project.security_class == "gatekeeping":
            security_emoji = "🚪"  # Door emoji for gatekeeping
        else:
            security_emoji = "🌐"  # Globe emoji for online

        lines = [
            Text(f"Project:   {project.id} {security_emoji}"),
            Text(upstream),
            Text(""),
            Text.assemble("Dockerfiles: ", docker_s),
            Text.assemble("Images:      ", images_s),
            Text.assemble("SSH dir:     ", ssh_s),
            Text.assemble("Git gate:    ", gate_s),
            tasks_line,
        ]

        # Add gate commit info if available
        gate_commit = state.get("gate_last_commit")
        if gate_commit:
            lines.append(Text(""))
            lines.append(Text("Gate info:"))
            lines.append(Text(f"  Commit:   {gate_commit.get('commit_hash', 'unknown')[:8]}"))
            lines.append(Text(f"  Date:     {gate_commit.get('commit_date', 'unknown')}"))
            lines.append(Text(f"  Author:   {gate_commit.get('commit_author', 'unknown')}"))
            message = gate_commit.get("commit_message", "unknown")
            message = message[:50] + ("..." if len(message) > 50 else "")
            lines.append(Text(f"  Message:  {message}"))

        # Add upstream staleness info if available (gatekeeping projects only)
        if staleness is not None:
            lines.append(Text(""))
            lines.append(Text("Upstream status:"))
            if staleness.error:
                lines.append(Text(f"  Error:    {staleness.error}"))
            elif staleness.is_stale:
                behind_str = "unknown"
                if staleness.commits_behind is not None:
                    behind_str = str(staleness.commits_behind)
                lines.append(
                    Text(f"  Status:   BEHIND ({behind_str} commits) on {staleness.branch}")
                )
                upstream_head = (
                    staleness.upstream_head[:8] if staleness.upstream_head else "unknown"
                )
                gate_head = staleness.gate_head[:8] if staleness.gate_head else "unknown"
                lines.append(Text(f"  Upstream: {upstream_head}"))
                lines.append(Text(f"  Gate:     {gate_head}"))
            else:
                lines.append(Text(f"  Status:   Up to date on {staleness.branch}"))
                gate_head = staleness.gate_head[:8] if staleness.gate_head else "unknown"
                lines.append(Text(f"  Commit:   {gate_head}"))
            lines.append(Text(f"  Checked:  {staleness.last_checked}"))

        self.update(Text("\n").join(lines))


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
        self.update(Text(self.message or ""))
