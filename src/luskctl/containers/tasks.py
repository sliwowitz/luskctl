import os
import shlex
import shutil
import subprocess
from pathlib import Path

import yaml  # pip install pyyaml

from .._util.logging_utils import _log_debug
from .._util.podman import _podman_userns_args
from ..core.config import state_root
from ..core.images import project_cli_image, project_web_image
from ..core.projects import Project, load_project
from ..ui.terminal import (
    blue as _blue,
)
from ..ui.terminal import (
    green as _green,
)
from ..ui.terminal import (
    red as _red,
)
from ..ui.terminal import (
    supports_color as _supports_color,
)
from ..ui.terminal import (
    yellow as _yellow,
)
from .agents import _prepare_agent_config_dir
from .environment import (
    _apply_web_env_overrides,
    _build_task_env_and_volumes,
    _ensure_dir,
)
from .ports import _assign_web_port
from .runtime import (
    _get_container_state,
    _gpu_run_args,
    _is_container_running,
    _stop_task_containers,
    _stream_initial_logs,
    _wait_for_exit,
    container_name,
)


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
    if exit_code is not None:
        meta["exit_code"] = exit_code
        meta["status"] = "completed" if exit_code == 0 else "failed"
    else:
        meta["status"] = "failed"
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
    _ensure_dir(tasks_root)
    meta_dir = _tasks_meta_dir(project.id)
    _ensure_dir(meta_dir)

    # Simple ID: numeric increment
    existing = sorted([p.stem for p in meta_dir.glob("*.yml") if p.stem.isdigit()], key=int)
    next_id = str(int(existing[-1]) + 1 if existing else 1)

    ws = tasks_root / next_id
    _ensure_dir(ws)

    # Create the workspace subdirectory and place a marker file to signal
    # that this is a fresh task. The init script will reset to latest HEAD
    # when it sees this marker, then remove it. See docstring above.
    workspace_dir = ws / "workspace"
    _ensure_dir(workspace_dir)
    marker_path = workspace_dir / ".new-task-marker"
    marker_path.write_text(
        "# This marker signals that the workspace should be reset to the latest remote HEAD.\n"
        "# It is created by 'luskctl task new' and removed by init-ssh-and-repo.sh after reset.\n"
        "# If you see this file in an initialized workspace, something went wrong.\n",
        encoding="utf-8",
    )

    meta = {
        "task_id": next_id,
        "status": "created",
        "mode": None,
        "workspace": str(ws),
        "web_port": None,
    }
    (meta_dir / f"{next_id}.yml").write_text(yaml.safe_dump(meta))
    print(f"Created task {next_id} in {ws}")
    return next_id


def get_tasks(project_id: str, reverse: bool = False) -> list[dict]:
    meta_dir = _tasks_meta_dir(project_id)
    tasks: list[dict] = []
    if not meta_dir.is_dir():
        return tasks
    for f in meta_dir.glob("*.yml"):
        try:
            tasks.append(yaml.safe_load(f.read_text()) or {})
        except Exception:
            continue
    tasks.sort(key=lambda d: int(d.get("task_id", 0)), reverse=reverse)
    return tasks


def task_list(project_id: str) -> None:
    tasks = get_tasks(project_id)
    if not tasks:
        print("No tasks found")
        return
    for t in tasks:
        tid = t.get("task_id", "?")
        status = t.get("status", "unknown")
        mode = t.get("mode")
        port = t.get("web_port")
        extra = []
        if mode:
            extra.append(f"mode={mode}")
        if port:
            extra.append(f"port={port}")
        extra_s = f" [{'; '.join(extra)}]" if extra else ""
        print(f"- {tid}: {status}{extra_s}")


def _check_mode(meta: dict, expected: str) -> None:
    mode = meta.get("mode")
    if mode and mode != expected:
        raise SystemExit(f"Task already ran in mode '{mode}', cannot run in '{expected}'")


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
    _stop_task_containers(project, str(task_id))
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
    state = _get_container_state(cname)
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


def task_run_cli(project_id: str, task_id: str, agents: list[str] | None = None) -> None:
    project = load_project(project_id)
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text()) or {}
    _check_mode(meta, "cli")

    cname = container_name(project.id, "cli", task_id)
    container_state = _get_container_state(cname)

    # If container already exists, handle it
    if container_state is not None:
        color_enabled = _supports_color()
        if container_state == "running":
            print(f"Container {_green(cname, color_enabled)} is already running.")
            login_cmd = f"luskctl login {project.id} {task_id}"
            raw_cmd = f"podman exec -it {cname} bash"
            print(f"Login with: {_blue(login_cmd, color_enabled)}")
            print(f"  (or:      {_blue(raw_cmd, color_enabled)})")
            return
        else:
            # Container exists but is stopped/exited - start it
            print(f"Starting existing container {_green(cname, color_enabled)}...")
            try:
                subprocess.run(
                    ["podman", "start", cname],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                raise SystemExit(
                    "Failed to start container: 'podman' executable not found. "
                    "Please install podman or ensure it is available on your PATH."
                )
            except subprocess.CalledProcessError as e:
                raise SystemExit(f"Failed to start container: {e}")
            meta["status"] = "running"
            meta["mode"] = "cli"
            meta_path.write_text(yaml.safe_dump(meta))
            print("Container started.")
            login_cmd = f"luskctl login {project.id} {task_id}"
            raw_cmd = f"podman exec -it {cname} bash"
            print(f"Login with: {_blue(login_cmd, color_enabled)}")
            print(f"  (or:      {_blue(raw_cmd, color_enabled)})")
            return

    env, volumes = _build_task_env_and_volumes(project, task_id)

    # Prepare agent-config dir (subagents from project YAML, filtered by default/selected)
    subagents = list(project.agent_config.get("subagents") or [])
    agent_config_dir = _prepare_agent_config_dir(project, task_id, subagents, agents)
    volumes.append(f"{agent_config_dir}:/home/dev/.luskctl:Z")

    # Run detached and keep the container alive so users can exec into it later
    # Note: We intentionally do NOT use --rm so containers persist after stopping.
    # This allows `task restart` to quickly resume stopped containers.
    cmd = ["podman", "run", "-d"]
    cmd += _podman_userns_args()
    cmd += _gpu_run_args(project)
    # Volumes
    for v in volumes:
        cmd += ["-v", v]
    # Environment
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    # Name, workdir, image and command
    cmd += [
        "--name",
        cname,
        "-w",
        "/workspace",
        project_cli_image(project.id),
        # Ensure init runs and then keep the container alive even without a TTY
        # init-ssh-and-repo.sh now prints a readiness marker we can watch for
        "bash",
        "-lc",
        "init-ssh-and-repo.sh && echo __CLI_READY__; tail -f /dev/null",
    ]
    print("$", " ".join(map(str, cmd)))
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE)
    except FileNotFoundError:
        raise SystemExit("podman not found; please install podman")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Run failed: {e}")

    # Stream initial logs until ready marker is seen (or timeout), then detach
    _stream_initial_logs(
        container_name=cname,
        timeout_sec=60.0,
        ready_check=lambda line: "__CLI_READY__" in line or ">> init complete" in line,
    )

    # Mark task as started (not completed) for CLI mode
    meta["status"] = "running"
    meta["mode"] = "cli"
    meta_path.write_text(yaml.safe_dump(meta))

    color_enabled = _supports_color()
    login_cmd = f"luskctl login {project.id} {task_id}"
    raw_cmd = f"podman exec -it {cname} bash"
    stop_command = f"podman stop {cname}"

    print(
        "\nCLI container is running in the background."
        f"\n- Name:     {_green(cname, color_enabled)}"
        f"\n- To enter: {_blue(login_cmd, color_enabled)}"
        f"\n  (or:      {_blue(raw_cmd, color_enabled)})"
        f"\n- To stop:  {_red(stop_command, color_enabled)}\n"
    )


def task_run_web(
    project_id: str,
    task_id: str,
    backend: str | None = None,
    agents: list[str] | None = None,
) -> None:
    project = load_project(project_id)
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text()) or {}
    _check_mode(meta, "web")

    mode_updated = meta.get("mode") != "web"
    if mode_updated:
        meta["mode"] = "web"

    port = meta.get("web_port")
    port_updated = False
    if not isinstance(port, int):
        port = _assign_web_port()
        meta["web_port"] = port
        port_updated = True

    env, volumes = _build_task_env_and_volumes(project, task_id)

    # Prepare agent-config dir (subagents from project YAML, filtered by default/selected)
    subagents = list(project.agent_config.get("subagents") or [])
    agent_config_dir = _prepare_agent_config_dir(project, task_id, subagents, agents)
    volumes.append(f"{agent_config_dir}:/home/dev/.luskctl:Z")

    env = _apply_web_env_overrides(env, backend, project.default_agent)

    # Save the effective backend to task metadata for UI display
    effective_backend = env.get("LUSKUI_BACKEND", "codex")
    backend_updated = meta.get("backend") != effective_backend
    if backend_updated:
        meta["backend"] = effective_backend

    # Write metadata once if anything was updated
    if port_updated or backend_updated or mode_updated:
        meta_path.write_text(yaml.safe_dump(meta))

    cname = container_name(project.id, "web", task_id)
    container_state = _get_container_state(cname)

    # If container already exists, handle it
    if container_state is not None:
        color_enabled = _supports_color()
        url = f"http://127.0.0.1:{port}/"
        if container_state == "running":
            print(f"Container {_green(cname, color_enabled)} is already running.")
            print(f"Web UI: {_blue(url, color_enabled)}")
            return
        else:
            # Container exists but is stopped/exited - start it
            print(f"Starting existing container {_green(cname, color_enabled)}...")
            try:
                subprocess.run(
                    ["podman", "start", cname],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                raise SystemExit(
                    "Failed to start container: 'podman' executable not found. "
                    "Please install podman or ensure it is available on your PATH."
                )
            except subprocess.CalledProcessError as e:
                raise SystemExit(f"Failed to start container: {e}")
            meta["status"] = "running"
            meta_path.write_text(yaml.safe_dump(meta))
            print("Container started.")
            print(f"Web UI: {_blue(url, color_enabled)}")
            return

    # Start UI in background and return terminal when it's reachable
    # Note: We intentionally do NOT use --rm so containers persist after stopping.
    # This allows `task restart` to quickly resume stopped containers.
    cmd = ["podman", "run", "-d", "-p", f"127.0.0.1:{port}:7860"]
    cmd += _podman_userns_args()
    cmd += _gpu_run_args(project)
    # Volumes
    for v in volumes:
        cmd += ["-v", v]
    # Environment
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += [
        "--name",
        cname,
        "-w",
        "/workspace",
        project_web_image(project.id),
    ]
    print("$", " ".join(map(str, cmd)))
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE)
    except FileNotFoundError:
        raise SystemExit("podman not found; please install podman")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Run failed: {e}")

    # Stream initial logs and detach once the LuskUI server reports that it
    # is actually running. We intentionally rely on a *log marker* here
    # instead of just probing the TCP port, because podman exposes the host port
    # regardless of the state of the routed guest port.
    # LuskUI currently prints a stable line when the server is ready, e.g.:
    #   "LuskUI started"
    #
    # We treat the appearance of this as the readiness signal.
    def _web_ready(line: str) -> bool:
        line = line.strip()
        if not line:
            return False

        # Primary marker: the main startup banner emitted by LuskUI when
        # the HTTP server is ready to accept connections.
        return "LuskUI started" in line

    # Follow logs until either the LuskUI readiness marker is seen or the
    # container exits. We deliberately do *not* time out here: as long as the
    # init script keeps making progress, the user sees the live logs and can
    # decide to Ctrl+C if it hangs.
    ready = _stream_initial_logs(
        container_name=cname,
        timeout_sec=None,
        ready_check=_web_ready,
    )

    # After log streaming stops, check whether the container is actually
    # still running. This prevents false "Web UI is up" messages in cases where
    # the web process failed to start (e.g. Node error) and the container
    # exited before emitting the readiness marker.
    running = _is_container_running(cname)

    if ready and running:
        if meta.get("status") != "running":
            meta["status"] = "running"
            meta_path.write_text(yaml.safe_dump(meta))
        color_enabled = _supports_color()
        print("\n\n>> luskctl: ")
        print("Web UI container is up")
    elif not running:
        print(
            "Web UI container exited before the web UI became reachable. "
            "Check the container logs for errors."
        )
        print(
            f"- Last known name: {cname}\n"
            f"- Check logs (if still available): podman logs {cname}\n"
            f"- You may need to re-run: luskctl task run-web {project.id} {task_id}"
        )
        # Exit with non-zero status to signal that the web UI did not start.
        raise SystemExit(1)

    url = f"http://127.0.0.1:{port}/"
    log_command = f"podman logs -f {cname}"
    stop_command = f"podman stop {cname}"

    print(
        f"- Name: {_green(cname, color_enabled)}"
        f"\n- Routed URL: {_blue(url, color_enabled)}"
        f"\n- Check logs: {_yellow(log_command, color_enabled)}"
        f"\n- Stop:       {_red(stop_command, color_enabled)}"
    )


def _print_run_summary(workspace: Path) -> None:
    """Print a summary of changes made by the headless agent."""
    try:
        diff_stat = subprocess.check_output(
            ["git", "-C", str(workspace), "diff", "--stat", "HEAD@{1}..HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if diff_stat:
            print("\n── Changes ──────────────────────────────")
            print(diff_stat)
        else:
            print("\n── No changes committed ──────────────────")
        print(f"  Workspace: {workspace}")
    except subprocess.CalledProcessError:
        print(f"\n  Workspace: {workspace}")
    except FileNotFoundError:
        print(f"\n  Workspace: {workspace}")


def task_run_headless(
    project_id: str,
    prompt: str,
    config_path: str | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    timeout: int | None = None,
    follow: bool = True,
    agents: list[str] | None = None,
) -> str:
    """Run Claude headlessly (autopilot mode) in a new task container.

    Creates a new task, prepares the agent-config directory with the claude
    wrapper function and filtered subagents, then launches a detached container
    that runs init-ssh-and-repo.sh followed by the claude command.

    Returns the task_id.
    """
    project = load_project(project_id)

    # Load CLI config file if provided (adds subagents to project's list)
    extra_subagents: list[dict] = []
    if config_path:
        config_src = Path(config_path)
        if not config_src.is_file():
            raise SystemExit(f"Agent config file not found: {config_path}")
        cli_config = yaml.safe_load(config_src.read_text(encoding="utf-8")) or {}
        extra_subagents = cli_config.get("subagents", []) or []

    # Create a new task
    task_id = task_new(project_id)

    # Collect subagents from project + config file
    subagents = list(project.agent_config.get("subagents") or []) + extra_subagents

    # Prepare agent-config dir with wrapper, agents.json, prompt.txt
    task_dir = project.tasks_root / str(task_id)
    agent_config_dir = _prepare_agent_config_dir(
        project,
        task_id,
        subagents,
        agents,
        prompt=prompt,
    )

    # Build env and volumes
    env, volumes = _build_task_env_and_volumes(project, task_id)

    # Mount agent-config dir to /home/dev/.luskctl
    volumes.append(f"{agent_config_dir}:/home/dev/.luskctl:Z")

    effective_timeout = timeout or 1800

    # Build CLI flags for model/max_turns (passed directly in headless command)
    claude_flags = ""
    if model:
        claude_flags += f" --model {shlex.quote(model)}"
    if max_turns:
        claude_flags += f" --max-turns {int(max_turns)}"

    # Build podman command (DETACHED)
    # NOTE (#180): The headless command passes --dangerously-skip-permissions,
    # --add-dir /, --agents, and git env vars directly instead of relying on
    # the claude() bash wrapper function from luskctl-claude.sh.  This is
    # because `timeout` is an external command that exec's `claude` from
    # PATH — it bypasses bash functions entirely.  The wrapper is still used
    # for interactive sessions where the user types `claude` at the prompt.
    # Ideally the wrapper and headless paths should share a single source of
    # truth for these flags; see #180.
    cname = container_name(project.id, "run", task_id)

    # Agents flag: load from agents.json if it was written
    agents_flag = ""
    agents_json_path = agent_config_dir / "agents.json"
    if agents_json_path.exists():
        agents_flag = ' --agents "$(cat /home/dev/.luskctl/agents.json)"'

    # Git identity env vars (same as the wrapper function provides)
    human_name = shlex.quote(project.human_name or "Nobody")
    human_email = shlex.quote(project.human_email or "nobody@localhost")
    git_env = (
        f"GIT_AUTHOR_NAME=Claude"
        f" GIT_AUTHOR_EMAIL=noreply@anthropic.com"
        f" GIT_COMMITTER_NAME=${{HUMAN_GIT_NAME:-{human_name}}}"
        f" GIT_COMMITTER_EMAIL=${{HUMAN_GIT_EMAIL:-{human_email}}}"
    )

    headless_cmd = (
        f"init-ssh-and-repo.sh && {git_env}"
        f" timeout {effective_timeout}"
        f' claude --dangerously-skip-permissions --add-dir "/"'
        f"{agents_flag}"
        f" -p "
        '"$(cat /home/dev/.luskctl/prompt.txt)"'
        f"{claude_flags} --output-format stream-json --verbose"
    )
    cmd: list[str] = ["podman", "run", "-d"]
    cmd += _podman_userns_args()
    cmd += _gpu_run_args(project)
    for v in volumes:
        cmd += ["-v", v]
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += [
        "--name",
        cname,
        "-w",
        "/workspace",
        project_cli_image(project.id),
        "bash",
        "-lc",
        headless_cmd,
    ]
    print("$", " ".join(map(str, cmd)))
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE)
    except FileNotFoundError:
        raise SystemExit("podman not found; please install podman")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Run failed: {e}")

    # Update task metadata
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    meta = yaml.safe_load(meta_path.read_text()) or {}
    meta["status"] = "running"
    meta["mode"] = "run"
    meta_path.write_text(yaml.safe_dump(meta))

    color_enabled = _supports_color()

    if follow:
        exit_code = _wait_for_exit(cname)
        _print_run_summary(task_dir / "workspace")

        update_task_exit_code(project.id, task_id, exit_code)

        if exit_code != 0:
            print(f"\nClaude exited with code {_red(str(exit_code), color_enabled)}")
    else:
        log_command = f"podman logs -f {cname}"
        stop_command = f"podman stop {cname}"
        print(
            f"\nHeadless Claude task started (detached)."
            f"\n- Task:  {task_id}"
            f"\n- Name:  {_green(cname, color_enabled)}"
            f"\n- Logs:  {_blue(log_command, color_enabled)}"
            f"\n- Stop:  {_red(stop_command, color_enabled)}\n"
        )

    return task_id


def task_stop(project_id: str, task_id: str) -> None:
    """Gracefully stop a running task container.

    Uses `podman stop` (with default 10s timeout) instead of force-removing.
    Updates task metadata status to 'stopped'.
    """
    project = load_project(project_id)
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text()) or {}

    mode = meta.get("mode")
    if not mode:
        raise SystemExit(f"Task {task_id} has never been run (no mode set)")

    cname = container_name(project.id, mode, task_id)

    state = _get_container_state(cname)
    if state is None:
        raise SystemExit(f"Task {task_id} container does not exist")
    if state not in ("running", "paused"):
        raise SystemExit(f"Task {task_id} container is not stoppable (state: {state})")

    try:
        subprocess.run(
            ["podman", "stop", cname],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise SystemExit("podman not found; please install podman")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Failed to stop container: {e}")

    meta["status"] = "stopped"
    meta_path.write_text(yaml.safe_dump(meta))

    color_enabled = _supports_color()
    print(f"Stopped task {task_id}: {_green(cname, color_enabled)}")
    print(f"Restart with: luskctl task restart {project_id} {task_id}")


def task_restart(project_id: str, task_id: str, backend: str | None = None) -> None:
    """Restart a stopped task or re-run if the container is gone.

    If the container exists in stopped/exited state, uses `podman start`.
    If the container doesn't exist, delegates to task_run_cli or task_run_web.
    """
    project = load_project(project_id)
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text()) or {}

    mode = meta.get("mode")
    if not mode:
        raise SystemExit(f"Task {task_id} has never been run (no mode set)")

    cname = container_name(project.id, mode, task_id)
    container_state = _get_container_state(cname)

    if container_state == "running":
        color_enabled = _supports_color()
        print(f"Task {task_id} is already running: {_green(cname, color_enabled)}")
        return

    if container_state is not None:
        # Container exists but is stopped/exited - restart it
        try:
            subprocess.run(
                ["podman", "start", cname],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise SystemExit("podman not found; please install podman")
        except subprocess.CalledProcessError as e:
            raise SystemExit(f"Failed to start container: {e}")

        meta["status"] = "running"
        meta_path.write_text(yaml.safe_dump(meta))

        color_enabled = _supports_color()
        print(f"Restarted task {task_id}: {_green(cname, color_enabled)}")
        if mode == "cli":
            login_cmd = f"luskctl login {project_id} {task_id}"
            raw_cmd = f"podman exec -it {cname} bash"
            print(f"Login with: {_blue(login_cmd, color_enabled)}")
            print(f"  (or:      {_blue(raw_cmd, color_enabled)})")
        elif mode == "web":
            port = meta.get("web_port")
            if port:
                print(f"Web UI: http://127.0.0.1:{port}/")
    else:
        # Container doesn't exist - re-run the task
        print(f"Container {cname} not found, re-running task...")
        if mode == "cli":
            task_run_cli(project_id, task_id)
        elif mode == "web":
            task_run_web(project_id, task_id, backend=backend or meta.get("backend"))
        else:
            raise SystemExit(f"Unknown mode '{mode}' for task {task_id}")


def task_status(project_id: str, task_id: str) -> None:
    """Show actual container state vs metadata state for a task."""
    project = load_project(project_id)
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text()) or {}

    mode = meta.get("mode")
    metadata_status = meta.get("status", "unknown")
    web_port = meta.get("web_port")

    color_enabled = _supports_color()

    # Get actual container state if mode is set
    container_state = None
    cname = None
    if mode:
        cname = container_name(project.id, mode, task_id)
        container_state = _get_container_state(cname)

    # Determine if there's a mismatch
    # Metadata "running" or "created" with mode should have a running container
    expected_running = metadata_status in ("running", "created") and mode is not None
    actual_running = container_state == "running"
    mismatch = expected_running and not actual_running

    print(f"Task {task_id}:")
    print(f"  Metadata status: {metadata_status}")
    print(f"  Mode:            {mode or 'not set'}")
    if cname:
        print(f"  Container:       {cname}")
    if container_state:
        state_color = _green if container_state == "running" else _yellow
        print(f"  Container state: {state_color(container_state, color_enabled)}")
    else:
        print(f"  Container state: {_red('not found', color_enabled)}")
    if web_port:
        print(f"  Web port:        {web_port}")
    if mismatch:
        print(
            f"\n  {_yellow('Warning:', color_enabled)} Metadata says running but container is not!"
        )
        print(f"  Run 'luskctl task restart {project_id} {task_id}' to fix.")
