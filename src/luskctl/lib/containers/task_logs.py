"""Task log viewing and streaming.

Provides the ``task_logs`` function for viewing formatted container logs.
Split from ``tasks.py`` to isolate log streaming, signal handling, and
formatter selection from task metadata management.
"""

import os
import subprocess

import yaml

from ..core.projects import load_project
from .log_format import auto_detect_formatter
from .runtime import container_name, get_container_state
from .tasks import tasks_meta_dir


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
    meta_dir = tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}

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
        stderr_output = b""
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        try:
            stderr_output = proc.stderr.read() or b""
        except (OSError, ValueError):
            pass
        formatter.finish()

    # Report podman errors if process failed and wasn't interrupted
    if not interrupted and proc.returncode and proc.returncode != 0:
        stderr_text = stderr_output.decode("utf-8", errors="replace").strip()
        if stderr_text:
            print(f"Warning: podman logs exited with code {proc.returncode}: {stderr_text}")

    if interrupted:
        print()
