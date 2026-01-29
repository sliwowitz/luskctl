import os
import select
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml  # pip install pyyaml

from .config import get_envs_base_dir, get_ui_base_port, state_root
from .fs import _ensure_dir_writable
from .images import project_cli_image, project_web_image
from .podman import _podman_userns_args
from .projects import Project, load_project


def _supports_color() -> bool:
    if "NO_COLOR" in os.environ:
        return False
    return sys.stdout.isatty()


def _color(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def _yellow(text: str, enabled: bool) -> str:
    return _color(text, "33", enabled)


def _blue(text: str, enabled: bool) -> str:
    return _color(text, "34", enabled)


def _green(text: str, enabled: bool) -> str:
    return _color(text, "32", enabled)


def _red(text: str, enabled: bool) -> str:
    return _color(text, "31", enabled)


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


@dataclass(frozen=True)
class ClipboardHelperStatus:
    available: tuple[str, ...]
    hint: str | None = None


@dataclass(frozen=True)
class ClipboardCopyResult:
    ok: bool
    method: str | None = None
    error: str | None = None
    hint: str | None = None


def _clipboard_install_hint() -> str:
    if sys.platform == "darwin":
        return ""

    # Wayland vs X11 is fuzzy; provide a useful Ubuntu/Debian hint.
    wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(
        os.environ.get("WAYLAND_DISPLAY")
    )
    x11 = os.environ.get("XDG_SESSION_TYPE") == "x11" or bool(os.environ.get("DISPLAY"))

    if wayland and not x11:
        return "Install wl-clipboard: sudo apt install wl-clipboard"
    if x11 and not wayland:
        return "Install xclip or xsel: sudo apt install xclip"
    return "Install wl-clipboard (Wayland) or xclip/xsel (X11)"


def _clipboard_candidates() -> list[tuple[str, list[str]]]:
    candidates: list[tuple[str, list[str]]] = []

    if sys.platform == "darwin":
        candidates.append(("pbcopy", ["pbcopy"]))
        return candidates
    if os.name == "nt":
        candidates.append(("clip", ["clip"]))
        return candidates

    wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland" or bool(
        os.environ.get("WAYLAND_DISPLAY")
    )
    x11 = os.environ.get("XDG_SESSION_TYPE") == "x11" or bool(os.environ.get("DISPLAY"))

    if wayland:
        candidates.append(("wl-copy", ["wl-copy", "--type", "text/plain"]))
    if x11:
        candidates.append(("xclip", ["xclip", "-selection", "clipboard"]))
        candidates.append(("xsel", ["xsel", "--clipboard", "--input"]))

    if not candidates:
        candidates.extend(
            [
                ("wl-copy", ["wl-copy", "--type", "text/plain"]),
                ("xclip", ["xclip", "-selection", "clipboard"]),
                ("xsel", ["xsel", "--clipboard", "--input"]),
            ]
        )

    return candidates


def get_clipboard_helper_status() -> ClipboardHelperStatus:
    """Return which clipboard helpers are available on this machine."""

    candidates = _clipboard_candidates()
    available = tuple(name for name, cmd in candidates if shutil.which(cmd[0]))
    if available:
        return ClipboardHelperStatus(available=available)

    hint = _clipboard_install_hint()
    return ClipboardHelperStatus(available=(), hint=hint or None)


def copy_to_clipboard_detailed(text: str) -> ClipboardCopyResult:
    """Copy text to the system clipboard and return a detailed result.

    Prefers native OS clipboard helpers when available. On Linux, users may
    need to install a helper (for example, ``wl-clipboard`` on Wayland or
    ``xclip``/``xsel`` on X11).

    Args:
        text: The text to copy to the system clipboard. If this is an empty
            string, the function will not invoke any clipboard helper and will
            return a failure result.

    Returns:
        ClipboardCopyResult: A dataclass describing the outcome:

            * ``ok``: ``True`` if the text was successfully written to the
              clipboard using one of the available helpers; ``False`` if all
              helpers failed or no helper was available, or if ``text`` was
              empty.
            * ``method``: The name of the clipboard helper that succeeded
              (for example, ``"pbcopy"``, ``"wl-copy"``, or ``"xclip"``) when
              ``ok`` is ``True``. ``None`` if no helper was run or all helpers
              failed.
            * ``error``: A human-readable error message describing why the
              copy failed when ``ok`` is ``False``. This is ``"Nothing to copy."``
              when ``text`` is empty, ``"No clipboard helper found on PATH."``
              when no helper is available, or the last recorded helper failure
              message when all helpers fail.
            * ``hint``: An optional hint string with guidance on how to enable
              clipboard support on the current platform (for example, a command
              to install a missing helper). This is typically populated when no
              helper is available or when all helpers fail, and is ``None`` on
              successful copies.

    Examples:
        Basic usage with boolean check::

            result = copy_to_clipboard_detailed("hello world")
            if result.ok:
                print(f"Copied to clipboard using {result.method}")
            else:
                print(f"Copy failed: {result.error}")
                if result.hint:
                    print(result.hint)

        Handling the case where no clipboard helper is installed::

            result = copy_to_clipboard_detailed("some text")
            if not result.ok and result.error == "No clipboard helper found on PATH.":
                # result.hint may contain a command to install a suitable helper.
                print(result.hint or "Install a clipboard helper for your system.")

        Handling an empty string (nothing to copy)::

            result = copy_to_clipboard_detailed("")
            assert not result.ok
            assert result.error == "Nothing to copy."
    """
    if not text:
        return ClipboardCopyResult(ok=False, error="Nothing to copy.")

    candidates = _clipboard_candidates()
    available = [(name, cmd) for name, cmd in candidates if shutil.which(cmd[0])]
    if not available:
        hint = _clipboard_install_hint()
        return ClipboardCopyResult(
            ok=False, error="No clipboard helper found on PATH.", hint=hint or None
        )

    errors: list[str] = []
    for name, cmd in available:
        try:
            subprocess.run(cmd, input=text, check=True, text=True, capture_output=True)
            return ClipboardCopyResult(ok=True, method=name)
        except subprocess.CalledProcessError as e:
            detail = (e.stderr or e.stdout or "").strip()
            errors.append(f"{name} failed" + (f": {detail}" if detail else ""))
        except Exception as e:
            errors.append(f"{name} error: {e}")

    hint = _clipboard_install_hint()
    return ClipboardCopyResult(
        ok=False, error=errors[-1] if errors else "Clipboard copy failed.", hint=hint or None
    )


def copy_to_clipboard(text: str) -> bool:
    """Backward-compatible clipboard copy helper returning only success."""
    return copy_to_clipboard_detailed(text).ok


# ---------- Tasks ----------

WEB_BACKENDS = ("codex", "claude", "mistral")
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


def task_new(project_id: str) -> None:
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


def _gpu_run_args(project: Project) -> list[str]:
    """Return additional podman run args to enable NVIDIA GPU if configured.

    Per-project only: GPUs are enabled exclusively by the project's project.yml.
    Default is disabled. Global config and environment variables are ignored.

    project.yml example:
      run:
        gpus: all   # or true

    When enabled, we pass a combination that works with Podman +
    nvidia-container-toolkit (recent versions):
      --device nvidia.com/gpu=all
      -e NVIDIA_VISIBLE_DEVICES=all
      -e NVIDIA_DRIVER_CAPABILITIES=all
      (optional) --hooks-dir=/usr/share/containers/oci/hooks.d if it exists
    """
    # Project-level setting from project.yml (only source of truth)
    enabled = False
    try:
        proj_cfg = yaml.safe_load((project.root / "project.yml").read_text()) or {}
        run_cfg = proj_cfg.get("run", {}) or {}
        gpus = run_cfg.get("gpus", run_cfg.get("gpu"))
        if isinstance(gpus, str):
            enabled = gpus.lower() == "all"
        elif isinstance(gpus, bool):
            enabled = gpus
    except Exception:
        enabled = False

    if not enabled:
        return []

    args: list[str] = [
        "--device",
        "nvidia.com/gpu=all",
        "-e",
        "NVIDIA_VISIBLE_DEVICES=all",
        "-e",
        "NVIDIA_DRIVER_CAPABILITIES=all",
    ]
    hooks_dir = Path("/usr/share/containers/oci/hooks.d")
    if hooks_dir.is_dir():
        args.extend(["--hooks-dir", str(hooks_dir)])
    return args


def _check_mode(meta: dict, expected: str) -> None:
    mode = meta.get("mode")
    if mode and mode != expected:
        raise SystemExit(f"Task already ran in mode '{mode}', cannot run in '{expected}'")


def _stop_task_containers(project: "Project", task_id: str) -> None:
    """Best-effort removal of any containers associated with a task.

    We intentionally ignore most errors here: task deletion should succeed
    even if podman isn't installed, the containers are already gone, or the
    container names never existed. This helper is used when deleting a
    task's workspace/metadata to avoid leaving behind containers that would
    later conflict with a new task reusing the same ID.

    We use ``podman rm -f`` rather than ``podman stop`` to make teardown
    deterministic and avoid hangs waiting for graceful shutdown inside the
    container. The task itself is already being deleted at this point, so
    a forceful remove is acceptable and keeps state consistent.
    """

    # The naming scheme is kept in sync with task_run_cli/task_run_ui.
    names = [
        f"{project.id}-cli-{task_id}",
        f"{project.id}-web-{task_id}",
    ]

    for name in names:
        try:
            _log_debug(f"stop_containers: podman rm -f {name} (start)")
            # "podman rm -f" force-removes the container even if it is
            # currently running. If the container does not exist this will
            # fail, but we treat that as a non-fatal condition and simply
            # continue.
            subprocess.run(
                ["podman", "rm", "-f", name],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _log_debug(f"stop_containers: podman rm -f {name} (done)")
        except FileNotFoundError:
            # podman not installed; nothing we can do here.
            _log_debug("stop_containers: podman not found; skipping all")
            break


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


def task_run_cli(project_id: str, task_id: str) -> None:
    project = load_project(project_id)
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text()) or {}
    _check_mode(meta, "cli")

    env, volumes = _build_task_env_and_volumes(project, task_id)

    # Run detached and keep the container alive so users can exec into it later
    cmd = ["podman", "run", "--rm", "-d"]
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
    login_command = f"podman exec -it {container_name} bash"
    stop_command = f"podman stop {container_name}"

    print(
        "\nCLI container is running in the background."
        f"\n- Name: {_green(container_name, color_enabled)}"
        f"\n- To enter: {_blue(login_command, color_enabled)}"
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

    # Start UI in background and return terminal when it's reachable
    cmd = ["podman", "run", "--rm", "-d", "-p", f"127.0.0.1:{port}:7860"]
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


def _is_container_running(container_name: str) -> bool:
    """Return True if a podman container with the given name is running.

    This uses `podman inspect` and treats missing containers or any
    inspection error as "not running".
    """
    try:
        out = subprocess.check_output(
            ["podman", "inspect", "-f", "{{.State.Running}}", container_name],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return out.lower() == "true"


def _stream_initial_logs(container_name: str, timeout_sec: float | None, ready_check) -> bool:
    """Follow container logs and detach when ready, timed out, or container exits.

    - container_name: podman container name.
    - timeout_sec: maximum seconds to follow logs. If ``None``, there is no
      time-based cutoff and we only stop when either the ready condition is
      met or the container exits.
    - ready_check: callable(line:str)->bool that returns True when ready. It will
      be evaluated for each incoming log line; for UI case it may ignore line
      content and probe external readiness.

    Returns True if a ready condition was met, False on timeout or if logs
    ended without ever becoming ready.
    """
    try:
        proc = subprocess.Popen(
            ["podman", "logs", "-f", container_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception:
        return False

    start = time.time()
    ready = False
    try:
        assert proc.stdout is not None
        while True:
            # Stop if timeout (when enabled)
            if timeout_sec is not None and (time.time() - start > timeout_sec):
                break
            # If process already ended, stop
            if proc.poll() is not None:
                break
            # Wait for a line (non-blocking with select)
            rlist, _, _ = select.select([proc.stdout], [], [], 0.5)
            if not rlist:
                # Even without a new line, allow external readiness checks
                if ready_check(""):
                    ready = True
                    break
                continue
            line = proc.stdout.readline()
            if not line:
                continue
            # Echo the line to the user's terminal
            try:
                sys.stdout.write(line)
                sys.stdout.flush()
            except Exception:
                # Ignore terminal write errors.
                pass
            # Check readiness based on the line content
            try:
                if ready_check(line):
                    ready = True
                    break
            except Exception:
                # Ignore errors in readiness checks
                pass
    finally:
        # Stop following logs
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
        except Exception:
            # Best-effort termination; ignore cleanup errors.
            pass
    return ready
