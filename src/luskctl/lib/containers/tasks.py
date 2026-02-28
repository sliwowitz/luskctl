"""Task metadata, lifecycle, and query operations.

Container runner functions (``task_run_cli``, ``task_run_web``,
``task_run_headless``, ``task_restart``) live in the companion
``task_runners`` module to keep this file focused on task metadata
management.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml  # pip install pyyaml

from .._util.ansi import (
    green as _green,
    red as _red,
    supports_color as _supports_color,
    yellow as _yellow,
)
from .._util.fs import ensure_dir
from .._util.logging_utils import _log_debug
from ..core.config import state_root
from ..core.projects import Project, load_project
from .log_format import auto_detect_formatter
from .runtime import (
    container_name,
    get_container_state,
    get_project_container_states,
    stop_task_containers,
)

# ---------- Status & mode display infrastructure ----------


@dataclass(frozen=True)
class StatusInfo:
    """Display attributes for a task effective status."""

    label: str
    emoji: str
    color: str


@dataclass(frozen=True)
class ModeInfo:
    """Display attributes for a task mode."""

    emoji: str
    label: str


STATUS_DISPLAY: dict[str, StatusInfo] = {
    "running": StatusInfo(label="running", emoji="▶️", color="green"),
    "stopped": StatusInfo(label="stopped", emoji="⏸️", color="yellow"),
    "completed": StatusInfo(label="completed", emoji="✅", color="green"),
    "failed": StatusInfo(label="failed", emoji="❌", color="red"),
    "created": StatusInfo(label="created", emoji="🆕", color="dim"),
    "not found": StatusInfo(label="not found", emoji="❓", color="yellow"),
    "deleting": StatusInfo(label="deleting", emoji="🗑️", color="yellow"),
}

MODE_DISPLAY: dict[str | None, ModeInfo] = {
    "cli": ModeInfo(emoji="⌨️", label="CLI"),
    "web": ModeInfo(emoji="🕸️", label="Web"),
    "run": ModeInfo(emoji="🚀", label="Autopilot"),
    None: ModeInfo(emoji="🦗", label=""),
}

WEB_BACKEND_EMOJI: dict[str, str] = {
    "claude": "✴️",
    "codex": "🌸",
    "mistral": "🏰",
    "copilot": "🤖",
}

_WEB_BACKEND_DEFAULT_EMOJI = "🕸️"


def effective_status(task: "TaskMeta") -> str:
    """Compute the display status from task metadata + live container state.

    Reads the following fields from a ``TaskMeta`` instance:

    - ``container_state`` (str | None): live podman state, or None
    - ``mode`` (str | None): task mode (cli/web/run/None)
    - ``exit_code`` (int | None): process exit code, or None
    - ``deleting`` (bool): ephemeral TUI-only flag

    Returns one of: ``"deleting"``, ``"running"``, ``"stopped"``,
    ``"completed"``, ``"failed"``, ``"created"``, ``"not found"``.
    """
    if task.deleting:
        return "deleting"

    cs = task.container_state
    mode = task.mode
    exit_code = task.exit_code

    if cs == "running":
        return "running"

    if cs is not None:
        # Container exists but is not running
        if exit_code is not None and exit_code == 0:
            return "completed"
        if exit_code is not None and exit_code != 0:
            return "failed"
        return "stopped"

    # No container found
    if mode is None:
        return "created"
    if exit_code is not None and exit_code == 0:
        return "completed"
    if exit_code is not None and exit_code != 0:
        return "failed"
    return "not found"


def mode_emoji(task: "TaskMeta") -> str:
    """Return the mode emoji for a task, resolving web backends.

    For ``mode="web"``, the emoji is looked up from ``WEB_BACKEND_EMOJI``
    using the task's ``backend`` field.  Other modes use ``MODE_DISPLAY``.
    """
    mode = task.mode
    if mode == "web":
        backend = task.backend
        if isinstance(backend, str):
            return WEB_BACKEND_EMOJI.get(backend, _WEB_BACKEND_DEFAULT_EMOJI)
        return _WEB_BACKEND_DEFAULT_EMOJI
    info = MODE_DISPLAY.get(mode if isinstance(mode, str) else None)
    return info.emoji if info else MODE_DISPLAY[None].emoji


@dataclass
class TaskMeta:
    """Lightweight metadata snapshot for a single task."""

    task_id: str
    mode: str | None
    workspace: str
    web_port: int | None
    backend: str | None = None
    container_state: str | None = None
    exit_code: int | None = None
    deleting: bool = False
    preset: str | None = None

    @property
    def status(self) -> str:
        """Compute effective status from live container state + metadata."""
        return effective_status(self)


def get_workspace_git_diff(project_id: str, task_id: str, against: str = "HEAD") -> str | None:
    """Get git diff from a task's workspace.

    Args:
        project_id: The project ID
        task_id: The task ID
        against: What to diff against ("HEAD" or "PREV")

    Returns:
        The git diff output as a string, or None if failed
    """
    try:
        project = load_project(project_id)
        tasks_root = project.tasks_root
        workspace_dir = tasks_root / task_id / "workspace"

        if not workspace_dir.exists() or not workspace_dir.is_dir():
            return None

        # Check if this is a git repository
        git_dir = workspace_dir / ".git"
        if not git_dir.exists():
            return None

        # Determine what to diff against
        if against == "PREV":
            # Diff against previous commit
            cmd = ["git", "-C", str(workspace_dir), "diff", "HEAD~1", "HEAD"]
        else:
            # Default: diff against HEAD (uncommitted changes)
            cmd = ["git", "-C", str(workspace_dir), "diff", "HEAD"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            # Non-zero return code indicates an error; treat as failure
            return None

        # Successful run; stdout may be empty if there is no diff
        return result.stdout

    except Exception:
        # If anything goes wrong, return None - this is a best-effort operation
        return None


# ---------- Tasks ----------


def _tasks_meta_dir(project_id: str) -> Path:
    """Return the directory containing task metadata YAML files for *project_id*."""
    return state_root() / "projects" / project_id / "tasks"


def update_task_exit_code(project_id: str, task_id: str, exit_code: int | None) -> None:
    """Update task metadata with exit code and final status.

    Args:
        project_id: The project ID
        task_id: The task ID
        exit_code: The exit code from the task, or None if unknown/failed
    """
    meta_dir = _tasks_meta_dir(project_id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        return
    meta = yaml.safe_load(meta_path.read_text()) or {}
    meta["exit_code"] = exit_code
    meta_path.write_text(yaml.safe_dump(meta))


def task_new(project_id: str) -> str:
    """Create a new task with a fresh workspace for a project.

    Workspace Initialization Protocol:
    ----------------------------------
    Each task gets its own workspace directory that persists across container
    runs. When a container starts, the init script (init-ssh-and-repo.sh) needs
    to know whether this is:

    1. A NEW task that should be reset to the latest remote HEAD
    2. A RESTARTED task where local changes should be preserved

    We use a marker file (.new-task-marker) to signal intent:

    - task_new() creates the marker in the workspace directory
    - init-ssh-and-repo.sh checks for the marker:
      - If marker exists: reset to origin/HEAD, then delete marker
      - If no marker: fetch only, preserve local state
    - Subsequent container runs on the same task won't see the marker,
      so local work is preserved

    This handles edge cases like:
    - Stale workspace from incompletely deleted previous task with same ID
    - Ensuring new tasks always start with latest code
    """
    project = load_project(project_id)
    tasks_root = project.tasks_root
    ensure_dir(tasks_root)
    meta_dir = _tasks_meta_dir(project.id)
    ensure_dir(meta_dir)

    # Simple ID: numeric increment
    existing = sorted([p.stem for p in meta_dir.glob("*.yml") if p.stem.isdigit()], key=int)
    next_id = str(int(existing[-1]) + 1 if existing else 1)

    ws = tasks_root / next_id
    ensure_dir(ws)

    # Create the workspace subdirectory and place a marker file to signal
    # that this is a fresh task. The init script will reset to latest HEAD
    # when it sees this marker, then remove it. See docstring above.
    workspace_dir = ws / "workspace"
    ensure_dir(workspace_dir)
    marker_path = workspace_dir / ".new-task-marker"
    marker_path.write_text(
        "# This marker signals that the workspace should be reset to the latest remote HEAD.\n"
        "# It is created by 'luskctl task new' and removed by init-ssh-and-repo.sh after reset.\n"
        "# If you see this file in an initialized workspace, something went wrong.\n",
        encoding="utf-8",
    )

    meta = {
        "task_id": next_id,
        "mode": None,
        "workspace": str(ws),
        "web_port": None,
    }
    (meta_dir / f"{next_id}.yml").write_text(yaml.safe_dump(meta))
    print(f"Created task {next_id} in {ws}")
    return next_id


def get_tasks(project_id: str, reverse: bool = False) -> list[TaskMeta]:
    """Return all task metadata for *project_id*, sorted by task ID."""
    meta_dir = _tasks_meta_dir(project_id)
    tasks: list[TaskMeta] = []
    if not meta_dir.is_dir():
        return tasks
    for f in meta_dir.glob("*.yml"):
        try:
            meta = yaml.safe_load(f.read_text()) or {}
            tasks.append(
                TaskMeta(
                    task_id=str(meta.get("task_id", "")),
                    mode=meta.get("mode"),
                    workspace=meta.get("workspace", ""),
                    web_port=meta.get("web_port"),
                    backend=meta.get("backend"),
                    exit_code=meta.get("exit_code"),
                    preset=meta.get("preset"),
                )
            )
        except Exception:
            continue
    tasks.sort(key=lambda t: int(t.task_id or 0), reverse=reverse)
    return tasks


def get_all_task_states(
    project_id: str,
    tasks: list[TaskMeta],
) -> dict[str, str | None]:
    """Map each task to its live container state via a single batch query.

    Args:
        project_id: The project whose containers to query.
        tasks: List of ``TaskMeta`` instances (must have ``task_id`` and ``mode``).

    Returns:
        ``{task_id: container_state_or_None}`` dict.
    """
    container_states = get_project_container_states(project_id)
    result: dict[str, str | None] = {}
    for t in tasks:
        if t.mode:
            cname = container_name(project_id, t.mode, str(t.task_id))
            result[str(t.task_id)] = container_states.get(cname)
        else:
            result[str(t.task_id)] = None
    return result


def task_list(
    project_id: str,
    *,
    status: str | None = None,
    mode: str | None = None,
    agent: str | None = None,
) -> None:
    """List tasks for a project, optionally filtered by status, mode, or agent preset.

    Status is computed live from podman container state + task metadata
    (never from the legacy ``status`` YAML field).
    """
    tasks = get_tasks(project_id)

    # Pre-filter by mode/agent before the podman query to reduce work
    if mode:
        tasks = [t for t in tasks if t.mode == mode]
    if agent:
        tasks = [t for t in tasks if t.preset == agent]

    if not tasks:
        print("No tasks found")
        return

    # Batch-query podman for all container states in one call
    live_states = get_all_task_states(project_id, tasks)
    for t in tasks:
        t.container_state = live_states.get(t.task_id)

    # Filter by effective status (computed live)
    if status:
        tasks = [t for t in tasks if effective_status(t) == status]

    if not tasks:
        print("No tasks found")
        return

    for t in tasks:
        t_status = effective_status(t)
        extra = []
        if t.mode:
            extra.append(f"mode={t.mode}")
        if t.web_port:
            extra.append(f"port={t.web_port}")
        extra_s = f" [{'; '.join(extra)}]" if extra else ""
        print(f"- {t.task_id}: {t_status}{extra_s}")


def _check_mode(meta: dict, expected: str) -> None:
    """Raise SystemExit if the task's mode conflicts with *expected*."""
    mode = meta.get("mode")
    if mode and mode != expected:
        raise SystemExit(f"Task already ran in mode '{mode}', cannot run in '{expected}'")


def load_task_meta(
    project_id: str, task_id: str, expected_mode: str | None = None
) -> tuple[dict, Path]:
    """Load task metadata and optionally validate mode.

    Returns (meta, meta_path). Raises SystemExit if task is unknown or mode
    conflicts with *expected_mode*.
    """
    meta_dir = _tasks_meta_dir(project_id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text()) or {}
    if expected_mode is not None:
        _check_mode(meta, expected_mode)
    return meta, meta_path


def task_delete(project_id: str, task_id: str) -> None:
    """Delete a task's workspace, metadata, and any associated containers.

    This mirrors the behavior used by the TUI when deleting a task, but is
    exposed here so both CLI and TUI share the same logic. Containers are
    stopped best-effort via podman using the naming scheme
    "<project.id>-<mode>-<task_id>".
    """
    _log_debug(f"task_delete: start project_id={project_id} task_id={task_id}")

    project = load_project(project_id)
    _log_debug("task_delete: loaded project")

    # Workspace lives under the project's tasks_root using the numeric ID.
    workspace = project.tasks_root / str(task_id)

    # Metadata lives in the per-project tasks state dir.
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    _log_debug(f"task_delete: workspace={workspace} meta_path={meta_path}")

    # Stop any matching containers first to avoid name conflicts if a new
    # task is later created with the same ID.
    _log_debug("task_delete: calling _stop_task_containers")
    stop_task_containers(project, str(task_id))
    _log_debug("task_delete: _stop_task_containers returned")

    if workspace.is_dir():
        _log_debug("task_delete: removing workspace directory")
        shutil.rmtree(workspace)
        _log_debug("task_delete: workspace directory removed")

    if meta_path.is_file():
        _log_debug("task_delete: removing metadata file")
        meta_path.unlink()
        _log_debug("task_delete: metadata file removed")

    _log_debug("task_delete: finished")


def _validate_login(project_id: str, task_id: str) -> tuple[str, str, Project]:
    """Validate that a task exists and its container is running.

    Returns (container_name, mode, project) on success.
    Raises SystemExit with actionable messages on failure.
    """
    project = load_project(project_id)
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text()) or {}

    mode = meta.get("mode")
    if not mode:
        raise SystemExit(
            f"Task {task_id} has never been run (no mode set). "
            f"Start it first via 'luskctl task run-cli {project_id} {task_id}' "
            f"or 'luskctl task run-web {project_id} {task_id}'."
        )

    cname = container_name(project.id, mode, task_id)
    state = get_container_state(cname)
    if state is None:
        raise SystemExit(
            f"Container {cname} does not exist. "
            f"Run 'luskctl task restart {project_id} {task_id}' first."
        )
    if state != "running":
        raise SystemExit(
            f"Container {cname} is not running (state: {state}). "
            f"Run 'luskctl task restart {project_id} {task_id}' first."
        )
    return cname, mode, project


def get_login_command(project_id: str, task_id: str) -> list[str]:
    """Return the podman exec command to log into a task container.

    Validates the task and container state, then returns the command
    list for use by TUI/tmux/terminal-spawn paths.

    Agent config is injected via the mount at container creation time,
    so no runtime injection is needed here.
    """
    cname, _mode, _project = _validate_login(project_id, task_id)
    return [
        "podman",
        "exec",
        "-it",
        cname,
        "tmux",
        "new-session",
        "-A",
        "-s",
        "main",
    ]


def task_login(project_id: str, task_id: str) -> None:
    """Open an interactive shell in a running task container.

    Validates the task, then replaces the current process with
    ``podman exec -it <container> tmux new-session -A -s main``.
    Raises SystemExit if podman is not found on PATH.
    """
    cmd = get_login_command(project_id, task_id)
    try:
        os.execvp(cmd[0], cmd)
    except FileNotFoundError:
        raise SystemExit(
            f"'{cmd[0]}' not found on PATH. Please install podman or add it to your PATH."
        )


def task_stop(project_id: str, task_id: str, *, timeout: int | None = None) -> None:
    """Gracefully stop a running task container.

    Uses ``podman stop --time <N>`` to give the container *timeout* seconds
    before SIGKILL.  When *timeout* is ``None`` the project's
    ``run.shutdown_timeout`` setting is used (default 10 s).
    Updates task metadata status to 'stopped'.
    """
    project = load_project(project_id)
    effective_timeout = timeout if timeout is not None else project.shutdown_timeout
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text()) or {}

    mode = meta.get("mode")
    if not mode:
        raise SystemExit(f"Task {task_id} has never been run (no mode set)")

    cname = container_name(project.id, mode, task_id)

    state = get_container_state(cname)
    if state is None:
        raise SystemExit(f"Task {task_id} container does not exist")
    if state not in ("running", "paused"):
        raise SystemExit(f"Task {task_id} container is not stoppable (state: {state})")

    try:
        subprocess.run(
            ["podman", "stop", "--time", str(effective_timeout), cname],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise SystemExit("podman not found; please install podman")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Failed to stop container: {e}")

    color_enabled = _supports_color()
    print(f"Stopped task {task_id}: {_green(cname, color_enabled)}")
    print(f"Restart with: luskctl task restart {project_id} {task_id}")


def task_logs(
    project_id: str,
    task_id: str,
    *,
    follow: bool = False,
    raw: bool = False,
    tail: int | None = None,
    streaming: bool = True,
) -> None:
    """View formatted logs for a task container.

    Works on both running and exited containers (podman logs supports both).

    Args:
        project_id: The project ID.
        task_id: The task ID.
        follow: Follow live output (``-f``).
        raw: Bypass formatting, show raw podman output.
        tail: Show only the last N lines.
        streaming: Enable partial streaming (typewriter effect) for supported formatters.
    """
    import select
    import signal

    project = load_project(project_id)
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text()) or {}

    mode = meta.get("mode")
    if not mode:
        raise SystemExit(
            f"Task {task_id} has never been run (no mode set). "
            f"Start it first via 'luskctl task run-cli {project_id} {task_id}'."
        )

    cname = container_name(project.id, mode, task_id)

    # Verify container exists (running or exited)
    state = get_container_state(cname)
    if state is None:
        raise SystemExit(
            f"Container {cname} does not exist. "
            f"Run 'luskctl task restart {project_id} {task_id}' first."
        )

    # Build podman logs command
    cmd = ["podman", "logs"]
    if follow:
        cmd.append("-f")
    if tail is not None:
        if tail < 0:
            raise SystemExit("--tail must be >= 0")
        cmd.extend(["--tail", str(tail)])
    cmd.append(cname)

    if raw:
        # Raw mode: exec podman directly, no formatting
        try:
            os.execvp(cmd[0], cmd)
        except FileNotFoundError:
            raise SystemExit("podman not found; please install podman")

    # Formatted mode: pipe through formatter
    formatter = auto_detect_formatter(mode, streaming=streaming)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise SystemExit("podman not found; please install podman")

    # Handle Ctrl+C gracefully
    interrupted = False
    original_sigint = signal.getsignal(signal.SIGINT)

    def _sigint_handler(signum, frame):
        """Set the interrupted flag on Ctrl+C."""
        nonlocal interrupted
        interrupted = True

    signal.signal(signal.SIGINT, _sigint_handler)

    try:
        buf = b""
        while not interrupted:
            if proc.poll() is not None:
                # Process exited — drain remaining output
                remaining = proc.stdout.read()
                if remaining:
                    buf += remaining
                break

            try:
                ready, _, _ = select.select([proc.stdout], [], [], 0.2)
                if not ready:
                    continue
                chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else b""
                if not chunk:
                    continue
                buf += chunk
            except (OSError, ValueError):
                break

            # Process complete lines
            while b"\n" in buf:
                raw_line, buf = buf.split(b"\n", 1)
                line = raw_line.decode("utf-8", errors="replace")
                formatter.feed_line(line)

        # Flush any trailing partial line
        if buf:
            line = buf.decode("utf-8", errors="replace")
            if line.strip():
                formatter.feed_line(line)
    finally:
        signal.signal(signal.SIGINT, original_sigint)
        # Check for stderr from podman before terminating
        stderr_output = b""
        try:
            stderr_output = proc.stderr.read() or b""
        except (OSError, ValueError):
            pass
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        formatter.finish()

    # Report podman errors if process failed and wasn't interrupted
    if not interrupted and proc.returncode and proc.returncode != 0:
        stderr_text = stderr_output.decode("utf-8", errors="replace").strip()
        if stderr_text:
            print(f"Warning: podman logs exited with code {proc.returncode}: {stderr_text}")

    if interrupted:
        print()


def task_status(project_id: str, task_id: str) -> None:
    """Show live task status with container state diagnostics."""
    project = load_project(project_id)
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text()) or {}

    mode = meta.get("mode")
    web_port = meta.get("web_port")
    exit_code = meta.get("exit_code")

    color_enabled = _supports_color()

    # Query live container state
    cname = None
    cs = None
    if mode:
        cname = container_name(project.id, mode, task_id)
        cs = get_container_state(cname)

    # Build TaskMeta for effective_status / mode_emoji computation
    task = TaskMeta(
        task_id=task_id,
        mode=mode,
        workspace=meta.get("workspace", ""),
        web_port=web_port,
        backend=meta.get("backend"),
        exit_code=exit_code,
        container_state=cs,
    )
    status = effective_status(task)
    info = STATUS_DISPLAY.get(status, STATUS_DISPLAY["created"])

    status_color = {"green": _green, "yellow": _yellow, "red": _red}.get(info.color, _yellow)
    m_emoji = mode_emoji(task)
    mode_info = MODE_DISPLAY.get(mode, MODE_DISPLAY[None])

    print(f"Task {task_id}:")
    print(f"  Status:          {info.emoji} {status_color(info.label, color_enabled)}")
    print(f"  Mode:            {m_emoji} {mode_info.label or 'not set'}")
    if cname:
        print(f"  Container:       {cname}")
    if cs:
        state_color = _green if cs == "running" else _yellow
        print(f"  Container state: {state_color(cs, color_enabled)}")
    elif mode:
        print(f"  Container state: {_red('not found', color_enabled)}")
    if exit_code is not None:
        print(f"  Exit code:       {exit_code}")
    if web_port:
        print(f"  Web port:        {web_port}")
