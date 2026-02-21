"""Container utility functions that can be safely imported by other modules."""

import subprocess
from collections.abc import Callable
from typing import Any

from .projects import Project


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


def _stop_task_containers(project: Any, task_id: str) -> None:
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
    from .logging_utils import _log_debug

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
        except Exception:
            # We intentionally ignore all errors here.
            pass


def _gpu_run_args(project: "Project") -> list[str]:
    """Return additional podman run args to enable NVIDIA GPU if configured.

    Per-project only: GPUs are enabled exclusively by the project's project.yml.
    Default is disabled. Global config and environment variables are ignored.
    """
    import yaml

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

    return args


def _stream_initial_logs(
    container_name: str,
    timeout_sec: float | None,
    ready_check: Callable[[str], bool],
) -> bool:
    """Stream logs from a container until ready marker is seen or timeout.

    Returns True if ready marker was found, False on timeout.
    """
    import sys
    import threading
    import time

    from .logging_utils import _log_debug

    # Mutable container so stream_logs can propagate its result back.
    holder: list[bool] = [False]

    def stream_logs() -> None:
        try:
            proc = subprocess.Popen(
                ["podman", "logs", "-f", container_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )

            start_time = time.time()

            while True:
                if timeout_sec is not None and time.time() - start_time >= timeout_sec:
                    break
                if proc.poll() is not None:
                    break

                try:
                    line = proc.stdout.readline()
                    if not line:
                        time.sleep(0.1)
                        continue

                    line = line.strip()
                    if line:
                        print(line, file=sys.stdout, flush=True)
                        if ready_check(line):
                            holder[0] = True
                            proc.terminate()
                            return
                except Exception as exc:
                    _log_debug(f"_stream_initial_logs readline error: {exc}")
                    break

            proc.terminate()
        except Exception as exc:
            _log_debug(f"_stream_initial_logs error: {exc}")

    stream_thread = threading.Thread(target=stream_logs)
    stream_thread.start()
    stream_thread.join(timeout_sec)

    return holder[0]


def _stream_until_exit(container_name: str, timeout_sec: float | None = None) -> int:
    """Wait for a container to exit and return its exit code.

    Returns the container's exit code, 124 on timeout, or 1 if podman is not found.
    """
    try:
        proc = subprocess.run(
            ["podman", "wait", container_name],
            check=False,
            capture_output=True,
            timeout=timeout_sec,
        )
        stdout = proc.stdout.decode().strip() if isinstance(proc.stdout, bytes) else proc.stdout
        if stdout:
            return int(stdout)
        return proc.returncode
    except subprocess.TimeoutExpired:
        return 124
    except subprocess.CalledProcessError as e:
        return e.returncode if e.returncode else 1
    except (FileNotFoundError, ValueError):
        return 1
