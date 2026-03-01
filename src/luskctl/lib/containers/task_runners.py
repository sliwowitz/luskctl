"""Task container runners: CLI, web, headless, and restart.

Split from ``tasks.py`` to decompose the God Module.  This module handles
the ``podman run`` orchestration for each task mode while ``tasks.py``
retains task metadata, lifecycle, and query operations.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from ..core.images import project_cli_image, project_web_image
from ..core.projects import load_project
from ..util.ansi import (
    blue as _blue,
    green as _green,
    red as _red,
    supports_color as _supports_color,
    yellow as _yellow,
)
from ..util.podman import _podman_userns_args
from .agent_config import resolve_agent_config
from .agents import prepare_agent_config_dir
from .environment import (
    apply_web_env_overrides,
    build_task_env_and_volumes,
)
from .ports import assign_web_port
from .runtime import (
    container_name,
    get_container_state,
    gpu_run_args,
    is_container_running,
    stream_initial_logs,
    wait_for_exit,
)
from .tasks import (
    load_task_meta,
    task_new,
    update_task_exit_code,
)

if TYPE_CHECKING:
    from ..core.project_model import Project


def _run_container(
    *,
    cname: str,
    image: str,
    env: dict[str, str],
    volumes: list[str],
    project: Project,
    extra_args: list[str] | None = None,
    command: list[str] | None = None,
) -> None:
    """Build, print, and execute a detached ``podman run`` command.

    Centralises the shared container-launch boilerplate used by the CLI, web,
    and headless runners: user-namespace mapping, GPU passthrough, volume and
    environment injection, and uniform error handling.

    Args:
        cname: Container name (``--name``).
        image: Container image to run.
        env: Environment variables to pass via ``-e``.
        volumes: Volume mounts to pass via ``-v``.
        project: The resolved :class:`Project` (used for GPU args).
        extra_args: Additional ``podman run`` flags inserted after the GPU
            args (e.g. ``["-p", "127.0.0.1:8080:7860"]``).
        command: Optional command + args appended after the image name.
    """
    cmd: list[str] = ["podman", "run", "-d"]
    cmd += _podman_userns_args()
    cmd += gpu_run_args(project)
    if extra_args:
        cmd += extra_args
    for v in volumes:
        cmd += ["-v", v]
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += ["--name", cname, "-w", "/workspace", image]
    if command:
        cmd += command
    print("$", " ".join(map(str, cmd)))
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE)
    except FileNotFoundError:
        raise SystemExit("podman not found; please install podman")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Run failed: {e}")


def task_run_cli(
    project_id: str, task_id: str, agents: list[str] | None = None, preset: str | None = None
) -> None:
    """Launch a CLI-mode task container and wait for its readiness marker.

    Creates (or reattaches to) a detached Podman container for interactive
    CLI access.  After the container reports ready the task metadata is
    marked ``running`` and the user is shown login instructions.
    """
    project = load_project(project_id)
    meta, meta_path = load_task_meta(project.id, task_id, "cli")

    cname = container_name(project.id, "cli", task_id)
    container_state = get_container_state(cname)

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
            post_state = get_container_state(cname)
            if post_state != "running":
                raise SystemExit(
                    f"Container {cname} failed to start (state: {post_state}). "
                    f"Check logs with: podman logs {cname}"
                )
            meta["mode"] = "cli"
            meta_path.write_text(yaml.safe_dump(meta))
            print("Container started.")
            login_cmd = f"luskctl login {project.id} {task_id}"
            raw_cmd = f"podman exec -it {cname} bash"
            print(f"Login with: {_blue(login_cmd, color_enabled)}")
            print(f"  (or:      {_blue(raw_cmd, color_enabled)})")
            return

    env, volumes = build_task_env_and_volumes(project, task_id)

    # Resolve layered agent config (global → project → preset → CLI overrides)
    effective = resolve_agent_config(project_id, preset=preset)
    subagents = list(effective.get("subagents") or [])
    agent_config_dir = prepare_agent_config_dir(project, task_id, subagents, agents)
    volumes.append(f"{agent_config_dir}:/home/dev/.luskctl:Z")

    # Run detached and keep the container alive so users can exec into it later
    # Note: We intentionally do NOT use --rm so containers persist after stopping.
    # This allows `task restart` to quickly resume stopped containers.
    _run_container(
        cname=cname,
        image=project_cli_image(project.id),
        env=env,
        volumes=volumes,
        project=project,
        # Ensure init runs and then keep the container alive even without a TTY
        # init-ssh-and-repo.sh now prints a readiness marker we can watch for
        command=["bash", "-lc", "init-ssh-and-repo.sh && echo __CLI_READY__; tail -f /dev/null"],
    )

    # Stream initial logs until ready marker is seen (or timeout), then detach
    stream_initial_logs(
        container_name=cname,
        timeout_sec=60.0,
        ready_check=lambda line: "__CLI_READY__" in line or ">> init complete" in line,
    )

    # Verify the container is still alive after log streaming
    post_state = get_container_state(cname)
    if post_state != "running":
        raise SystemExit(
            f"Container {cname} exited unexpectedly (state: {post_state}). "
            f"Check logs with: podman logs {cname}"
        )

    meta["mode"] = "cli"
    if preset:
        meta["preset"] = preset
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
    preset: str | None = None,
) -> None:
    """Launch a web-mode task container with a browser-accessible IDE backend.

    Sets up port forwarding, starts a detached Podman container running
    the chosen *backend* (OpenHands or Open WebUI), and prints the URL
    the user can open in a browser.
    """
    project = load_project(project_id)
    meta, meta_path = load_task_meta(project.id, task_id, "web")

    mode_updated = meta.get("mode") != "web"
    if mode_updated:
        meta["mode"] = "web"

    preset_updated = False
    if preset and meta.get("preset") != preset:
        meta["preset"] = preset
        preset_updated = True

    port = meta.get("web_port")
    port_updated = False
    if not isinstance(port, int):
        port = assign_web_port()
        meta["web_port"] = port
        port_updated = True

    env, volumes = build_task_env_and_volumes(project, task_id)

    # Resolve layered agent config (global → project → preset → CLI overrides)
    effective = resolve_agent_config(project_id, preset=preset)
    subagents = list(effective.get("subagents") or [])
    agent_config_dir = prepare_agent_config_dir(project, task_id, subagents, agents)
    volumes.append(f"{agent_config_dir}:/home/dev/.luskctl:Z")

    env = apply_web_env_overrides(env, backend, project.default_agent)

    # Save the effective backend to task metadata for UI display
    effective_backend = env.get("LUSKUI_BACKEND", "codex")
    backend_updated = meta.get("backend") != effective_backend
    if backend_updated:
        meta["backend"] = effective_backend

    # Write metadata once if anything was updated
    if port_updated or backend_updated or mode_updated or preset_updated:
        meta_path.write_text(yaml.safe_dump(meta))

    cname = container_name(project.id, "web", task_id)
    container_state = get_container_state(cname)

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
            post_state = get_container_state(cname)
            if post_state != "running":
                raise SystemExit(
                    f"Container {cname} failed to start (state: {post_state}). "
                    f"Check logs with: podman logs {cname}"
                )
            print("Container started.")
            print(f"Web UI: {_blue(url, color_enabled)}")
            return

    # Start UI in background and return terminal when it's reachable
    # Note: We intentionally do NOT use --rm so containers persist after stopping.
    # This allows `task restart` to quickly resume stopped containers.
    _run_container(
        cname=cname,
        image=project_web_image(project.id),
        env=env,
        volumes=volumes,
        project=project,
        extra_args=["-p", f"127.0.0.1:{port}:7860"],
    )

    # Stream initial logs and detach once the LuskUI server reports that it
    # is actually running. We intentionally rely on a *log marker* here
    # instead of just probing the TCP port, because podman exposes the host port
    # regardless of the state of the routed guest port.
    # LuskUI currently prints a stable line when the server is ready, e.g.:
    #   "LuskUI started"
    #
    # We treat the appearance of this as the readiness signal.
    def _web_ready(line: str) -> bool:
        """Return True if *line* contains the LuskUI readiness marker."""
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
    ready = stream_initial_logs(
        container_name=cname,
        timeout_sec=None,
        ready_check=_web_ready,
    )

    # After log streaming stops, check whether the container is actually
    # still running. This prevents false "Web UI is up" messages in cases where
    # the web process failed to start (e.g. Node error) and the container
    # exited before emitting the readiness marker.
    running = is_container_running(cname)

    if ready and running:
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
    preset: str | None = None,
    name: str | None = None,
) -> str:
    """Run Claude headlessly (autopilot mode) in a new task container.

    Creates a new task, prepares the agent-config directory with the claude
    wrapper function and filtered subagents, then launches a detached container
    that runs init-ssh-and-repo.sh followed by the claude command.

    Args:
        name: Optional human-readable name.  Allowed characters are
            lowercase letters, digits, hyphens, and underscores.
            If ``None``, a random name is generated via
            :func:`generate_task_name`.

    Returns the task_id.
    """
    project = load_project(project_id)

    # Build CLI overrides from --config file and explicit flags
    cli_overrides: dict = {}
    if config_path:
        config_src = Path(config_path)
        if not config_src.is_file():
            raise SystemExit(f"Agent config file not found: {config_path}")
        cli_config = yaml.safe_load(config_src.read_text(encoding="utf-8")) or {}
        cli_overrides = cli_config

    # Resolve layered agent config (global → project → preset → CLI overrides)
    effective = resolve_agent_config(
        project_id, preset=preset, cli_overrides=cli_overrides if cli_overrides else None
    )

    # Create a new task
    task_id = task_new(project_id, name=name)

    # Collect subagents from resolved config
    subagents = list(effective.get("subagents") or [])

    # Prepare agent-config dir with wrapper, agents.json, prompt.txt
    task_dir = project.tasks_root / str(task_id)
    agent_config_dir = prepare_agent_config_dir(
        project,
        task_id,
        subagents,
        agents,
        prompt=prompt,
    )

    # Build env and volumes
    env, volumes = build_task_env_and_volumes(project, task_id)

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
    # The claude() wrapper from luskctl-claude.sh handles --dangerously-skip-permissions,
    # --add-dir /, --agents, git env vars, and (via --luskctl-timeout) the timeout.
    # Only per-run flags (model, max_turns, prompt) are passed here.
    cname = container_name(project.id, "run", task_id)

    headless_cmd = (
        f"init-ssh-and-repo.sh &&"
        f" claude --luskctl-timeout {effective_timeout}"
        f" -p "
        '"$(cat /home/dev/.luskctl/prompt.txt)"'
        f"{claude_flags} --output-format stream-json --verbose"
    )
    _run_container(
        cname=cname,
        image=project_cli_image(project.id),
        env=env,
        volumes=volumes,
        project=project,
        command=["bash", "-lc", headless_cmd],
    )

    # Update task metadata
    meta, meta_path = load_task_meta(project.id, task_id)
    meta["mode"] = "run"
    if preset:
        meta["preset"] = preset
    meta_path.write_text(yaml.safe_dump(meta))

    color_enabled = _supports_color()

    if follow:
        exit_code = wait_for_exit(cname)
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


def task_followup_headless(
    project_id: str,
    task_id: str,
    prompt: str,
    follow: bool = True,
) -> None:
    """Send a follow-up prompt to a completed/failed headless task.

    Updates prompt.txt in the existing agent-config directory and restarts
    the stopped container via ``podman start``.  The claude wrapper
    automatically resumes the previous session via ``--resume`` from
    ``claude-session.txt`` (written by the SessionStart hook).

    Per-run flags (model, max_turns, timeout) carry forward from the
    original ``task_run_headless`` invocation since ``podman start``
    re-executes the same container command.
    """
    project = load_project(project_id)
    meta, meta_path = load_task_meta(project.id, task_id)

    mode = meta.get("mode")
    if mode != "run":
        raise SystemExit(
            f"Task {task_id} is not a headless task (mode={mode!r}). "
            f"Follow-up is only supported for autopilot (mode='run') tasks."
        )

    cname = container_name(project.id, "run", task_id)
    container_state = get_container_state(cname)
    if container_state == "running":
        raise SystemExit(
            f"Container {cname} is still running. "
            f"Wait for it to finish or stop it before sending a follow-up."
        )
    if container_state is None:
        raise SystemExit(
            f"Container {cname} not found. Cannot follow up — the container may have been removed."
        )

    # Update prompt.txt with the new follow-up prompt (after all validation)
    task_dir = project.tasks_root / str(task_id)
    agent_config_dir = task_dir / "agent-config"
    (agent_config_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    # Restart the existing container (re-runs the original bash command,
    # which reads prompt.txt and claude-session.txt from the volume)
    try:
        subprocess.run(
            ["podman", "start", cname],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise SystemExit("podman not found; please install podman")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Failed to start container: {e}")

    # Verify the container actually started
    post_state = get_container_state(cname)
    if post_state != "running":
        raise SystemExit(
            f"Container {cname} failed to start for follow-up (state: {post_state}). "
            f"Check logs with: podman logs {cname}"
        )

    # Clear previous exit_code so effective_status shows "running" until new exit
    meta["exit_code"] = None
    meta_path.write_text(yaml.safe_dump(meta))

    color_enabled = _supports_color()

    if follow:
        exit_code = wait_for_exit(cname)
        _print_run_summary(task_dir / "workspace")

        update_task_exit_code(project.id, task_id, exit_code)

        if exit_code != 0:
            print(f"\nClaude exited with code {_red(str(exit_code), color_enabled)}")
    else:
        log_command = f"podman logs -f {cname}"
        stop_command = f"podman stop {cname}"
        print(
            f"\nFollow-up started (detached)."
            f"\n- Task:  {task_id}"
            f"\n- Name:  {_green(cname, color_enabled)}"
            f"\n- Logs:  {_blue(log_command, color_enabled)}"
            f"\n- Stop:  {_red(stop_command, color_enabled)}\n"
        )


def task_restart(project_id: str, task_id: str, backend: str | None = None) -> None:
    """Restart a task container.

    If the container is running, stops it first and then starts it again.
    If the container exists in stopped/exited state, uses ``podman start``.
    If the container doesn't exist, delegates to task_run_cli or task_run_web.

    Note:
        Headless (mode ``"run"``) tasks cannot be auto-restarted because they
        require the original prompt and context.  Attempting to restart a
        headless task whose container no longer exists will raise ``SystemExit``.
        Re-run headless tasks manually via ``luskctl run`` with the original
        prompt instead.
    """
    project = load_project(project_id)
    meta, meta_path = load_task_meta(project.id, task_id)

    mode = meta.get("mode")
    if not mode:
        raise SystemExit(f"Task {task_id} has never been run (no mode set)")

    cname = container_name(project.id, mode, task_id)
    container_state = get_container_state(cname)

    print(f"Restarting task {project_id}/{task_id} ({mode})...")

    if container_state == "running":
        # Container is running - stop it first, then start it again
        try:
            subprocess.run(
                ["podman", "stop", "--time", str(project.shutdown_timeout), cname],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise SystemExit("podman not found; please install podman")
        except subprocess.CalledProcessError as e:
            raise SystemExit(f"Failed to stop container: {e}")

    if container_state is not None:
        # Container exists (stopped/exited, or just stopped above) - start it
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

        post_state = get_container_state(cname)
        if post_state != "running":
            raise SystemExit(
                f"Container {cname} failed to start (state: {post_state}). "
                f"Check logs with: podman logs {cname}"
            )

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
        saved_preset = meta.get("preset")
        if mode == "cli":
            task_run_cli(project_id, task_id, preset=saved_preset)
        elif mode == "web":
            task_run_web(
                project_id, task_id, backend=backend or meta.get("backend"), preset=saved_preset
            )
        else:
            raise SystemExit(f"Unknown mode '{mode}' for task {task_id}")
