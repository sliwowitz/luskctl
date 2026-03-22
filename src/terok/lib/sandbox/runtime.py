# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Container runtime gateway wrapping the Podman CLI.

Provides module-level functions for container lifecycle operations
(state queries, GPU args, log streaming, etc.).

All functions accept plain parameters (strings, paths) — no terok-specific
types like ``ProjectConfig``.  Container naming is orchestration policy and
lives in ``orchestration.tasks`` / ``orchestration.task_runners``.
"""

import subprocess
from collections.abc import Callable
from pathlib import Path

# ---------- Public functions ----------


def get_project_container_states(name_prefix: str) -> dict[str, str]:
    """Return ``{container_name: state}`` for all containers matching *name_prefix*.

    Uses a single ``podman ps -a`` call with a name filter instead of
    per-container ``podman inspect`` calls.  Returns an empty dict when
    podman is unavailable.
    """
    try:
        out = subprocess.check_output(
            [
                "podman",
                "ps",
                "-a",
                "--filter",
                f"name=^{name_prefix}-",
                "--format",
                "{{.Names}} {{.State}}",
                "--no-trunc",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}

    result: dict[str, str] = {}
    for line in out.strip().splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            result[parts[0]] = parts[1].lower()
    return result


def get_container_state(cname: str) -> str | None:
    """Return container state ('running', 'exited', ...) or ``None`` if not found."""
    try:
        out = subprocess.check_output(
            ["podman", "inspect", "-f", "{{.State.Status}}", cname],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out.lower() if out else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def is_container_running(cname: str) -> bool:
    """Return ``True`` if the named container is currently running."""
    try:
        out = subprocess.check_output(
            ["podman", "inspect", "-f", "{{.State.Running}}", cname],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return out.lower() == "true"


def stop_task_containers(container_names: list[str]) -> None:
    """Best-effort ``podman rm -f`` of the given containers.

    Ignores all errors so that task deletion succeeds even when podman is
    absent or the containers are already gone.
    """
    from ..util.logging_utils import _log_debug

    for name in container_names:
        try:
            _log_debug(f"stop_containers: podman rm -f {name} (start)")
            subprocess.run(
                ["podman", "rm", "-f", name],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
            )
            _log_debug(f"stop_containers: podman rm -f {name} (done)")
        except Exception:
            pass


def gpu_run_args(project_root: Path) -> list[str]:
    """Return additional ``podman run`` args to enable NVIDIA GPU if configured.

    Reads ``run.gpus`` from ``project.yml`` in *project_root*.
    """
    from terok.lib.util.yaml import load as _yaml_load

    enabled = False
    try:
        proj_cfg = _yaml_load((project_root / "project.yml").read_text()) or {}
        run_cfg = proj_cfg.get("run", {}) or {}
        gpus = run_cfg.get("gpus")
        if isinstance(gpus, str):
            enabled = gpus.lower() == "all"
        elif isinstance(gpus, bool):
            enabled = gpus
    except Exception:
        enabled = False

    if not enabled:
        return []

    return [
        "--device",
        "nvidia.com/gpu=all",
        "-e",
        "NVIDIA_VISIBLE_DEVICES=all",
        "-e",
        "NVIDIA_DRIVER_CAPABILITIES=all",
    ]


def stream_initial_logs(
    container_name: str,
    timeout_sec: float | None,
    ready_check: Callable[[str], bool],
) -> bool:
    """Stream logs until ready marker is seen or timeout.

    Returns ``True`` if the ready marker was found, ``False`` on timeout.
    """
    import select
    import sys
    import threading
    import time

    from ..util.logging_utils import _log_debug

    holder: list[bool] = [False]
    stop_event = threading.Event()
    proc_holder: list[subprocess.Popen | None] = [None]

    def _stream_logs() -> None:
        """Follow container logs in a thread, setting *holder[0]* on ready."""
        try:
            proc = subprocess.Popen(
                ["podman", "logs", "-f", container_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            proc_holder[0] = proc
            start_time = time.time()
            buf = b""

            while not stop_event.is_set():
                if timeout_sec is not None and time.time() - start_time >= timeout_sec:
                    break
                if proc.poll() is not None:
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
                except Exception as exc:
                    _log_debug(f"_stream_initial_logs read error: {exc}")
                    break

                while b"\n" in buf:
                    raw_line, buf = buf.split(b"\n", 1)
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if line:
                        print(line, file=sys.stdout, flush=True)
                        if ready_check(line):
                            holder[0] = True
                            proc.terminate()
                            return

            if buf:
                line = buf.decode("utf-8", errors="replace").strip()
                if line:
                    print(line, file=sys.stdout, flush=True)
                    if ready_check(line):
                        holder[0] = True

            proc.terminate()
        except Exception as exc:
            _log_debug(f"_stream_initial_logs error: {exc}")

    stream_thread = threading.Thread(target=_stream_logs)
    stream_thread.start()
    stream_thread.join(timeout_sec)

    if stream_thread.is_alive():
        stop_event.set()
        proc = proc_holder[0]
        if proc is not None:
            proc.terminate()
        stream_thread.join(timeout=5)

    return holder[0]


def wait_for_exit(cname: str, timeout_sec: float | None = None) -> int:
    """Wait for a container to exit and return its exit code.

    Returns 124 on timeout, 1 if podman is not found.
    """
    try:
        proc = subprocess.run(
            ["podman", "wait", cname],
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
    except (FileNotFoundError, ValueError):
        return 1
