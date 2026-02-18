import os
import shutil
import socket
import subprocess
from pathlib import Path

import yaml  # pip install pyyaml

from .config import get_envs_base_dir, get_ui_base_port, state_root
from .containers import (
    _get_container_state,
    _gpu_run_args,
    _is_container_running,
    _stop_task_containers,
    _stream_initial_logs,
)
from .fs import _ensure_dir_writable
from .images import project_cli_image, project_web_image
from .podman import _podman_userns_args
from .projects import Project, load_project
from .terminal import (
    blue as _blue,
)
from .terminal import (
    green as _green,
)
from .terminal import (
    red as _red,
)
from .terminal import (
    supports_color as _supports_color,
)
from .terminal import (
    yellow as _yellow,
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

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # Non-zero return code indicates an error; treat as failure
            return None

        # Successful run; stdout may be empty if there is no diff
        return result.stdout

    except Exception:
        # If anything goes wrong, return None - this is a best-effort operation
        return None


# ---------- Tasks ----------

WEB_BACKENDS = ("codex", "claude", "copilot", "mistral")
# Host-side env prefix for passthrough to container web UI.
WEB_ENV_PASSTHROUGH_PREFIX = "LUSKUI_"
WEB_ENV_PASSTHROUGH_KEYS = (
    "ANTHROPIC_API_KEY",
    "CLAUDE_API_KEY",
    "MISTRAL_API_KEY",
)


def _tasks_meta_dir(project_id: str) -> Path:
    return state_root() / "projects" / project_id / "tasks"


def _log_debug(message: str) -> None:
    """Append a simple debug line to the luskctl library log.

    This is intentionally very small and best-effort so it never interferes
    with normal CLI or TUI behavior. It can be used to compare behavior
    between different frontends (e.g. CLI vs TUI) when calling the shared
    helpers in this module.
    """

    try:
        from datetime import datetime as _dt
        from pathlib import Path as _Path

        log_path = _Path("/tmp/luskctl-lib.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = _dt.now().isoformat(timespec="seconds")
        with log_path.open("a", encoding="utf-8") as _f:
            _f.write(f"[luskctl DEBUG] {ts} {message}\n")
    except Exception:
        # Logging must never change behavior of library code.
        pass


def _ensure_dir(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)


def _normalize_web_backend(backend: str | None) -> str | None:
    if backend is None:
        return None
    backend = backend.strip()
    if not backend:
        return None
    return backend.lower()


def _apply_web_env_overrides(
    env: dict,
    backend: str | None,
    project_default_agent: str | None = None,
) -> dict:
    """Return a copy of env with web-specific overrides applied.

    Backend precedence (highest to lowest):
    1. Explicit backend argument (from CLI --backend flag)
    2. DEFAULT_AGENT environment variable on host
    3. project_default_agent (from project.yml or global config)
    4. Default: "codex"
    """
    merged = dict(env)

    # Determine effective backend with precedence
    effective_backend = _normalize_web_backend(backend)
    if not effective_backend:
        effective_backend = _normalize_web_backend(os.environ.get("DEFAULT_AGENT"))
    if not effective_backend:
        effective_backend = _normalize_web_backend(project_default_agent)
    if not effective_backend:
        effective_backend = "codex"

    # Export as LUSKUI_BACKEND to the container
    merged["LUSKUI_BACKEND"] = effective_backend

    for key, value in os.environ.items():
        if key.startswith(WEB_ENV_PASSTHROUGH_PREFIX) and key not in merged:
            merged[key] = value

    for key in WEB_ENV_PASSTHROUGH_KEYS:
        if key not in merged:
            val = os.environ.get(key)
            if val:
                merged[key] = val

    return merged


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


# ---------- Pod/port helpers ----------


def _is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _collect_all_web_ports() -> set[int]:
    # Scan all task metas for any project
    root = state_root() / "projects"
    ports: set[int] = set()
    if not root.is_dir():
        return ports
    for proj_dir in root.iterdir():
        tdir = proj_dir / "tasks"
        if not tdir.is_dir():
            continue
        for f in tdir.glob("*.yml"):
            try:
                meta = yaml.safe_load(f.read_text()) or {}
            except Exception:
                continue
            port = meta.get("web_port")
            if isinstance(port, int):
                ports.add(port)
    return ports


def _assign_web_port() -> int:
    used = _collect_all_web_ports()
    base = get_ui_base_port()
    port = base
    max_tries = 200
    tries = 0
    while tries < max_tries:
        if port not in used and _is_port_free(port):
            return port
        port += 1
        tries += 1
    raise SystemExit("No free web ports available")


def _build_task_env_and_volumes(project: Project, task_id: str) -> tuple[dict, list[str]]:
    """Compose environment and volume mounts for a task container.

    - Mount per-task workspace subdir to /workspace (host-explorable).
    - Mount shared codex config dir to /home/dev/.codex (read-write).
    - Mount shared Claude config dir to /home/dev/.claude (read-write).
    - Optionally mount per-project SSH config dir to /home/dev/.ssh (read-write).
    - Provide REPO_ROOT and git info for the init script.
    """
    # Per-task workspace directory as a subdirectory of the task dir
    task_dir = project.tasks_root / str(task_id)
    repo_dir = task_dir / "workspace"
    repo_dir.mkdir(parents=True, exist_ok=True)

    # Shared env mounts
    envs_base = get_envs_base_dir()
    codex_host_dir = envs_base / "_codex-config"
    claude_host_dir = envs_base / "_claude-config"
    vibe_host_dir = envs_base / "_vibe-config"
    blablador_host_dir = envs_base / "_blablador-config"
    opencode_config_host_dir = envs_base / "_opencode-config"
    opencode_data_host_dir = envs_base / "_opencode-data"
    opencode_state_host_dir = envs_base / "_opencode-state"
    # Prefer project-configured SSH host dir if set
    ssh_host_dir = project.ssh_host_dir or (envs_base / f"_ssh-config-{project.id}")
    _ensure_dir_writable(codex_host_dir, "Codex config")
    _ensure_dir_writable(claude_host_dir, "Claude config")
    _ensure_dir_writable(vibe_host_dir, "Vibe config")
    _ensure_dir_writable(blablador_host_dir, "Blablador config")
    _ensure_dir_writable(opencode_config_host_dir, "OpenCode config")
    _ensure_dir_writable(opencode_data_host_dir, "OpenCode data")
    _ensure_dir_writable(opencode_state_host_dir, "OpenCode state")

    env = {
        "PROJECT_ID": project.id,
        "TASK_ID": task_id,
        # Tell init script where to clone/sync the repo
        "REPO_ROOT": "/workspace",
        # Default reset mode is none; allow overriding via container env if needed
        "GIT_RESET_MODE": os.environ.get("LUSKCTL_GIT_RESET_MODE", "none"),
        # Keep Claude Code config under the shared mount regardless of HOME.
        "CLAUDE_CONFIG_DIR": "/home/dev/.claude",
        # Human credentials for git committer (AI agent is the author)
        "HUMAN_GIT_NAME": project.human_name or "Nobody",
        "HUMAN_GIT_EMAIL": project.human_email or "nobody@localhost",
    }

    volumes: list[str] = []

    # Per-task workspace mount (container-specific, not shared)
    volumes.append(f"{repo_dir}:/workspace:Z")

    # Shared codex credentials/config (shared between containers)
    volumes.append(f"{codex_host_dir}:/home/dev/.codex:z")
    # Shared Claude credentials/config (shared between containers)
    volumes.append(f"{claude_host_dir}:/home/dev/.claude:z")
    # Shared Mistral Vibe credentials/config (shared between containers)
    volumes.append(f"{vibe_host_dir}:/home/dev/.vibe:z")
    # Shared Blablador credentials/config (OpenCode wrapper, shared between containers)
    volumes.append(f"{blablador_host_dir}:/home/dev/.blablador:z")
    # Shared OpenCode config directory (shared between containers)
    volumes.append(f"{opencode_config_host_dir}:/home/dev/.config/opencode:z")
    # Shared OpenCode data directory (used by OpenCode/Blablador, shared between containers)
    volumes.append(f"{opencode_data_host_dir}:/home/dev/.local/share/opencode:z")
    # Shared OpenCode state directory (used by Bun runtime, shared between containers)
    volumes.append(f"{opencode_state_host_dir}:/home/dev/.local/state:z")

    # Security mode specific wiring
    gate_repo = project.gate_path
    gate_parent = gate_repo.parent
    # Mount point inside container for the gate
    gate_mount_inside = "/git-gate/gate.git"

    if project.security_class == "gatekeeping":
        # In gatekeeping mode, hide upstream and SSH. Use the host gate as the only remote.
        if not gate_repo.exists():
            raise SystemExit(
                f"Git gate missing for project '{project.id}'.\n"
                f"Expected at: {gate_repo}\n"
                f"Run 'luskctl gate-sync {project.id}' to create/update the local mirror."
            )

        # Ensure parent exists for mount consistency (gate should already exist)
        gate_parent.mkdir(parents=True, exist_ok=True)
        # Mount gate read-write so tasks can push branches for review (shared between project containers)
        volumes.append(f"{gate_repo}:{gate_mount_inside}:z")
        env["CODE_REPO"] = f"file://{gate_mount_inside}"
        env["GIT_BRANCH"] = project.default_branch or "main"
        # Optionally expose the upstream URL as an "external" remote.
        if project.expose_external_remote and project.upstream_url:
            env["EXTERNAL_REMOTE_URL"] = project.upstream_url
        # Optional SSH mount in gatekeeping mode (shared between project containers)
        if project.ssh_mount_in_gatekeeping and ssh_host_dir.is_dir():
            _ensure_dir_writable(ssh_host_dir, "SSH config")
            volumes.append(f"{ssh_host_dir}:/home/dev/.ssh:z")
    else:
        # Online mode: clone from gate if present, then set upstream to real URL
        if gate_repo.exists():
            gate_parent.mkdir(parents=True, exist_ok=True)
            # Mount gate read-only (shared between project containers)
            volumes.append(f"{gate_repo}:{gate_mount_inside}:z,ro")
            env["CLONE_FROM"] = f"file://{gate_mount_inside}"
        if project.upstream_url:
            env["CODE_REPO"] = project.upstream_url
            env["GIT_BRANCH"] = project.default_branch or "main"
        # Optional SSH config mount in online mode (configurable, shared between project containers)
        if project.ssh_mount_in_online and ssh_host_dir.is_dir():
            _ensure_dir_writable(ssh_host_dir, "SSH config")
            volumes.append(f"{ssh_host_dir}:/home/dev/.ssh:z")

    return env, volumes


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


def _validate_login(project_id: str, task_id: str) -> tuple[str, str]:
    """Validate that a task exists and its container is running.

    Returns (container_name, mode) on success.
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

    container_name = f"{project.id}-{mode}-{task_id}"
    state = _get_container_state(container_name)
    if state is None:
        raise SystemExit(
            f"Container {container_name} does not exist. "
            f"Run 'luskctl task restart {project_id} {task_id}' first."
        )
    if state != "running":
        raise SystemExit(
            f"Container {container_name} is not running (state: {state}). "
            f"Run 'luskctl task restart {project_id} {task_id}' first."
        )
    return container_name, mode


def get_login_command(project_id: str, task_id: str) -> list[str]:
    """Return the podman exec command to log into a task container.

    Validates the task and container state, then returns the command list
    for use by TUI/tmux/terminal-spawn paths.
    """
    container_name, _mode = _validate_login(project_id, task_id)
    return [
        "podman",
        "exec",
        "-it",
        container_name,
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


def task_run_cli(project_id: str, task_id: str) -> None:
    project = load_project(project_id)
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text()) or {}
    _check_mode(meta, "cli")

    container_name = f"{project.id}-cli-{task_id}"
    container_state = _get_container_state(container_name)

    # If container already exists, handle it
    if container_state is not None:
        color_enabled = _supports_color()
        if container_state == "running":
            print(f"Container {_green(container_name, color_enabled)} is already running.")
            login_cmd = f"luskctl login {project.id} {task_id}"
            raw_cmd = f"podman exec -it {container_name} bash"
            print(f"Login with: {_blue(login_cmd, color_enabled)}")
            print(f"  (or:      {_blue(raw_cmd, color_enabled)})")
            return
        else:
            # Container exists but is stopped/exited - start it
            print(f"Starting existing container {_green(container_name, color_enabled)}...")
            try:
                subprocess.run(
                    ["podman", "start", container_name],
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
            raw_cmd = f"podman exec -it {container_name} bash"
            print(f"Login with: {_blue(login_cmd, color_enabled)}")
            print(f"  (or:      {_blue(raw_cmd, color_enabled)})")
            return

    env, volumes = _build_task_env_and_volumes(project, task_id)

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
        f"{project.id}-cli-{task_id}",
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
        container_name=f"{project.id}-cli-{task_id}",
        timeout_sec=60.0,
        ready_check=lambda line: "__CLI_READY__" in line or ">> init complete" in line,
    )

    # Mark task as started (not completed) for CLI mode
    meta["status"] = "running"
    meta["mode"] = "cli"
    meta_path.write_text(yaml.safe_dump(meta))

    color_enabled = _supports_color()
    container_name = f"{project.id}-cli-{task_id}"
    login_cmd = f"luskctl login {project.id} {task_id}"
    raw_cmd = f"podman exec -it {container_name} bash"
    stop_command = f"podman stop {container_name}"

    print(
        "\nCLI container is running in the background."
        f"\n- Name:     {_green(container_name, color_enabled)}"
        f"\n- To enter: {_blue(login_cmd, color_enabled)}"
        f"\n  (or:      {_blue(raw_cmd, color_enabled)})"
        f"\n- To stop:  {_red(stop_command, color_enabled)}\n"
    )


def task_run_web(project_id: str, task_id: str, backend: str | None = None) -> None:
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
    env = _apply_web_env_overrides(env, backend, project.default_agent)

    # Save the effective backend to task metadata for UI display
    effective_backend = env.get("LUSKUI_BACKEND", "codex")
    backend_updated = meta.get("backend") != effective_backend
    if backend_updated:
        meta["backend"] = effective_backend

    # Write metadata once if anything was updated
    if port_updated or backend_updated or mode_updated:
        meta_path.write_text(yaml.safe_dump(meta))

    container_name = f"{project.id}-web-{task_id}"
    container_state = _get_container_state(container_name)

    # If container already exists, handle it
    if container_state is not None:
        color_enabled = _supports_color()
        url = f"http://127.0.0.1:{port}/"
        if container_state == "running":
            print(f"Container {_green(container_name, color_enabled)} is already running.")
            print(f"Web UI: {_blue(url, color_enabled)}")
            return
        else:
            # Container exists but is stopped/exited - start it
            print(f"Starting existing container {_green(container_name, color_enabled)}...")
            try:
                subprocess.run(
                    ["podman", "start", container_name],
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
        container_name,
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
        container_name=container_name,
        timeout_sec=None,
        ready_check=_web_ready,
    )

    # After log streaming stops, check whether the container is actually
    # still running. This prevents false "Web UI is up" messages in cases where
    # the web process failed to start (e.g. Node error) and the container
    # exited before emitting the readiness marker.
    running = _is_container_running(container_name)

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
            f"- Last known name: {container_name}\n"
            f"- Check logs (if still available): podman logs {container_name}\n"
            f"- You may need to re-run: luskctl task run-web {project.id} {task_id}"
        )
        # Exit with non-zero status to signal that the web UI did not start.
        raise SystemExit(1)

    url = f"http://127.0.0.1:{port}/"
    log_command = f"podman logs -f {container_name}"
    stop_command = f"podman stop {container_name}"

    print(
        f"- Name: {_green(container_name, color_enabled)}"
        f"\n- Routed URL: {_blue(url, color_enabled)}"
        f"\n- Check logs: {_yellow(log_command, color_enabled)}"
        f"\n- Stop:       {_red(stop_command, color_enabled)}"
    )


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

    container_name = f"{project.id}-{mode}-{task_id}"

    state = _get_container_state(container_name)
    if state is None:
        raise SystemExit(f"Task {task_id} container does not exist")
    if state not in ("running", "paused"):
        raise SystemExit(f"Task {task_id} container is not stoppable (state: {state})")

    try:
        subprocess.run(
            ["podman", "stop", container_name],
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
    print(f"Stopped task {task_id}: {_green(container_name, color_enabled)}")
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

    container_name = f"{project.id}-{mode}-{task_id}"
    container_state = _get_container_state(container_name)

    if container_state == "running":
        color_enabled = _supports_color()
        print(f"Task {task_id} is already running: {_green(container_name, color_enabled)}")
        return

    if container_state is not None:
        # Container exists but is stopped/exited - restart it
        try:
            subprocess.run(
                ["podman", "start", container_name],
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
        print(f"Restarted task {task_id}: {_green(container_name, color_enabled)}")
        if mode == "cli":
            login_cmd = f"luskctl login {project_id} {task_id}"
            raw_cmd = f"podman exec -it {container_name} bash"
            print(f"Login with: {_blue(login_cmd, color_enabled)}")
            print(f"  (or:      {_blue(raw_cmd, color_enabled)})")
        elif mode == "web":
            port = meta.get("web_port")
            if port:
                print(f"Web UI: http://127.0.0.1:{port}/")
    else:
        # Container doesn't exist - re-run the task
        print(f"Container {container_name} not found, re-running task...")
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
    container_name = None
    if mode:
        container_name = f"{project.id}-{mode}-{task_id}"
        container_state = _get_container_state(container_name)

    # Determine if there's a mismatch
    # Metadata "running" or "created" with mode should have a running container
    expected_running = metadata_status in ("running", "created") and mode is not None
    actual_running = container_state == "running"
    mismatch = expected_running and not actual_running

    print(f"Task {task_id}:")
    print(f"  Metadata status: {metadata_status}")
    print(f"  Mode:            {mode or 'not set'}")
    if container_name:
        print(f"  Container:       {container_name}")
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
