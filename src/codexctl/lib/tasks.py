from __future__ import annotations

import os
import select
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import yaml  # pip install pyyaml

from .config import get_envs_base_dir, get_ui_base_port, state_root
from .fs import _ensure_dir_writable
from .podman import _podman_userns_args
from .projects import Project, load_project


# ---------- Tasks ----------

def _tasks_meta_dir(project_id: str) -> Path:
    return state_root() / "projects" / project_id / "tasks"


def _log_debug(message: str) -> None:
    """Append a simple debug line to the codexctl library log.

    This is intentionally very small and best-effort so it never interferes
    with normal CLI or TUI behavior. It can be used to compare behavior
    between different frontends (e.g. CLI vs TUI) when calling the shared
    helpers in this module.
    """

    try:
        from datetime import datetime as _dt
        from pathlib import Path as _Path

        log_path = _Path("/tmp/codexctl-lib.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = _dt.now().isoformat(timespec="seconds")
        with log_path.open("a", encoding="utf-8") as _f:
            _f.write(f"[codexctl DEBUG] {ts} {message}\n")
    except Exception:
        # Logging must never change behavior of library code.
        pass


def _ensure_dir(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)


def task_new(project_id: str) -> None:
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

    meta = {
        "task_id": next_id,
        "status": "created",
        "mode": None,
        "workspace": str(ws),
        "ui_port": None,
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
        port = t.get("ui_port")
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


def _collect_all_ui_ports() -> set[int]:
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
            port = meta.get("ui_port")
            if isinstance(port, int):
                ports.add(port)
    return ports


def _assign_ui_port() -> int:
    used = _collect_all_ui_ports()
    base = get_ui_base_port()
    port = base
    max_tries = 200
    tries = 0
    while tries < max_tries:
        if port not in used and _is_port_free(port):
            return port
        port += 1
        tries += 1
    raise SystemExit("No free UI ports available")


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
    # Prefer project-configured SSH host dir if set
    ssh_host_dir = project.ssh_host_dir or (envs_base / f"_ssh-config-{project.id}")
    _ensure_dir_writable(codex_host_dir, "Codex config")
    _ensure_dir_writable(claude_host_dir, "Claude config")

    env = {
        "PROJECT_ID": project.id,
        "TASK_ID": task_id,
        # Tell init script where to clone/sync the repo
        "REPO_ROOT": "/workspace",
        # Default reset mode is none; allow overriding via container env if needed
        "GIT_RESET_MODE": os.environ.get("CODEXCTL_GIT_RESET_MODE", "none"),
        # Keep Claude Code config under the shared mount regardless of HOME.
        "CLAUDE_CONFIG_DIR": "/home/dev/.claude",
    }

    volumes: list[str] = []
    # Per-task workspace mount
    volumes.append(f"{repo_dir}:/workspace:Z")

    # Shared codex credentials/config
    volumes.append(f"{codex_host_dir}:/home/dev/.codex:Z")
    # Shared Claude credentials/config
    volumes.append(f"{claude_host_dir}:/home/dev/.claude:Z")

    # Security mode specific wiring
    cache_repo = project.cache_path
    cache_parent = cache_repo.parent
    # Mount point inside container for the cache
    cache_mount_inside = "/git-cache/cache.git"

    if project.security_class == "gatekept":
        # In gatekept mode, hide upstream and SSH. Use the host cache as the only remote.
        if not cache_repo.exists():
            raise SystemExit(
                f"Git cache missing for project '{project.id}'.\n"
                f"Expected at: {cache_repo}\n"
                f"Run 'codexctl cache-init {project.id}' to create/update the local mirror."
            )

        # Ensure parent exists for mount consistency (cache should already exist)
        cache_parent.mkdir(parents=True, exist_ok=True)
        # Mount cache read-write so tasks can push branches for review
        volumes.append(f"{cache_repo}:{cache_mount_inside}:Z")
        env["CODE_REPO"] = f"file://{cache_mount_inside}"
        env["GIT_BRANCH"] = project.default_branch or "main"
        # No SSH mount in gatekept
    else:
        # Online mode: clone from cache if present, then set upstream to real URL
        if cache_repo.exists():
            cache_parent.mkdir(parents=True, exist_ok=True)
            # Mount cache read-only
            volumes.append(f"{cache_repo}:{cache_mount_inside}:Z,ro")
            env["CLONE_FROM"] = f"file://{cache_mount_inside}"
        if project.upstream_url:
            env["CODE_REPO"] = project.upstream_url
            env["GIT_BRANCH"] = project.default_branch or "main"
        # Optional SSH config mount in online mode (configurable)
        if project.ssh_mount_in_online and ssh_host_dir.is_dir():
            _ensure_dir_writable(ssh_host_dir, "SSH config")
            volumes.append(f"{ssh_host_dir}:/home/dev/.ssh:Z")

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
        run_cfg = (proj_cfg.get("run", {}) or {})
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
        "--device", "nvidia.com/gpu=all",
        "-e", "NVIDIA_VISIBLE_DEVICES=all",
        "-e", "NVIDIA_DRIVER_CAPABILITIES=all",
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
        f"{project.id}-ui-{task_id}",
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
        "--name", f"{project.id}-cli-{task_id}",
        "-w", "/workspace",
        f"{project.id}:l2",
        # Ensure init runs and then keep the container alive even without a TTY
        # init-ssh-and-repo.sh now prints a readiness marker we can watch for
        "bash", "-lc", "init-ssh-and-repo.sh; echo __CLI_READY__; tail -f /dev/null",
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

    print(
        "\nCLI container is running in the background.\n"
        f"- Name: {project.id}-cli-{task_id}\n"
        f"- To enter: podman exec -it {project.id}-cli-{task_id} bash\n"
        f"- To stop:  podman stop {project.id}-cli-{task_id}\n"
    )


def task_run_ui(project_id: str, task_id: str) -> None:
    project = load_project(project_id)
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text()) or {}
    _check_mode(meta, "ui")

    port = meta.get("ui_port")
    if not isinstance(port, int):
        port = _assign_ui_port()
        meta["ui_port"] = port
        meta_path.write_text(yaml.safe_dump(meta))

    env, volumes = _build_task_env_and_volumes(project, task_id)

    container_name = f"{project.id}-ui-{task_id}"

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
        "--name", container_name,
        "-w", "/workspace",
        f"{project.id}:l3",
    ]
    print("$", " ".join(map(str, cmd)))
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE)
    except FileNotFoundError:
        raise SystemExit("podman not found; please install podman")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Run failed: {e}")

    # Stream initial logs and detach once the Codex UI server reports that it
    # is actually running. We intentionally rely on a *log marker* here
    # instead of just probing the TCP port, because podman exposes the host port
    # regardless of the state of the routed guest port.
    # Codex UI currently prints stable lines when the server is ready, e.g.:
    #   "Logging Codex UI activity to /var/log/codexui.log"
    #   "Codex UI (SDK streaming) on http://0.0.0.0:7860 - repo /workspace"
    #
    # We treat the appearance of either of these as the readiness signal.
    def _ui_ready(line: str) -> bool:
        line = line.strip()
        if not line:
            return False

        # Primary marker: the main startup banner emitted by Codex UI when
        # the HTTP server is ready to accept connections.
        if "Codex UI (" in line:
            return True

        # Secondary marker: log redirection message that currently appears at
        # roughly the same time as the banner above.
        if "Logging Codex UI activity" in line:
            return True

        return False

    # Follow logs until either the Codex UI readiness marker is seen or the
    # container exits. We deliberately do *not* time out here: as long as the
    # init script keeps making progress, the user sees the live logs and can
    # decide to Ctrl+C if it hangs.
    ready = _stream_initial_logs(
        container_name=container_name,
        timeout_sec=None,
        ready_check=_ui_ready,
    )

    # After log streaming stops, check whether the container is actually
    # still running. This prevents false "UI is up" messages in cases where
    # the UI process failed to start (e.g. Node error) and the container
    # exited before emitting the readiness marker.
    running = _is_container_running(container_name)

    if ready and running:
        print("\n\n>> codexctl: ")
        print(f"UI container is up, routed to: http://127.0.0.1:{port}")
    elif not running:
        print(
            "UI container exited before the web UI became reachable. "
            "Check the container logs for errors."
        )
        print(
            f"- Last known name: {container_name}\n"
            f"- Check logs (if still available): podman logs {container_name}\n"
            f"- You may need to re-run: codexctl task run-ui {project.id} {task_id}"
        )
        # Exit with non-zero status to signal that the UI did not start.
        raise SystemExit(1)

    print(
        f"- Name: {container_name}\n"
        f"- Check logs: podman logs -f {container_name}\n"
        f"- Stop:       podman stop {container_name}"
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


def _stream_initial_logs(container_name: str, timeout_sec: Optional[float], ready_check) -> bool:
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
