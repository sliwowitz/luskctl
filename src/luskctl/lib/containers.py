import select
import subprocess
import sys
import time
from pathlib import Path

import yaml

from .projects import Project, load_project


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


def _get_container_state(container_name: str) -> str | None:
    """Return container state: 'running', 'exited', 'paused', etc., or None if not found.

    This uses `podman inspect` to get the actual container state. Returns None
    if the container doesn't exist or podman is not available.
    """
    try:
        out = subprocess.check_output(
            ["podman", "inspect", "-f", "{{.State.Status}}", container_name],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out.lower() if out else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_task_container_state(project_id: str, task_id: str, mode: str | None) -> str | None:
    """Get actual container state for a task.

    This is intended for TUI background workers to check container status.
    Returns 'running', 'exited', 'paused', etc., or None if container not found.
    """
    if not mode:
        return None
    project = load_project(project_id)
    container_name = f"{project.id}-{mode}-{task_id}"
    return _get_container_state(container_name)


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
    from .tasks import _log_debug

    # The naming scheme is kept in sync with task_run_cli/task_run_web/task_run_headless.
    names = [
        f"{project.id}-cli-{task_id}",
        f"{project.id}-web-{task_id}",
        f"{project.id}-run-{task_id}",
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


def _get_container_exit_code(container_name: str) -> int:
    """Return the exit code of a stopped container. Returns -1 on error."""
    try:
        out = subprocess.check_output(
            ["podman", "inspect", "-f", "{{.State.ExitCode}}", container_name],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return int(out)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return -1


def _stream_until_exit(container_name: str, timeout_sec: float | None = None) -> int:
    """Stream container logs until the container exits. Returns exit code.

    This is used for headless/autopilot containers where the container runs
    a finite task (e.g. claude -p) and we want to stream all output until it
    completes, rather than detaching after a readiness marker.

    The ``timeout_sec`` parameter limits how long we follow logs, but this
    helper will still wait for the container to exit before returning an
    exit code.
    """
    _stream_initial_logs(
        container_name=container_name,
        timeout_sec=timeout_sec,
        ready_check=lambda line: False,  # never "ready", stream until exit
    )
    # Ensure the container has actually exited before reading its exit code.
    # _stream_initial_logs can stop due to timeout while the container
    # continues running; in that case we poll until it exits.
    while _is_container_running(container_name):
        time.sleep(0.5)
    return _get_container_exit_code(container_name)


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
