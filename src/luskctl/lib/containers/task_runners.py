"""Task container runners: CLI, web, headless, and restart.

Split from ``tasks.py`` to decompose the God Module.  This module handles
the ``podman run`` orchestration for each task mode while ``tasks.py``
retains task metadata, lifecycle, and query operations.
"""

import shlex
import subprocess
from pathlib import Path

import yaml

from .._util.ansi import (
    blue as _blue,
    green as _green,
    red as _red,
    supports_color as _supports_color,
    yellow as _yellow,
)
from .._util.podman import _podman_userns_args
from ..core.images import project_cli_image, project_web_image
from ..core.projects import load_project
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


def task_run_cli(project_id: str, task_id: str, agents: list[str] | None = None) -> None:
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
            meta["status"] = "running"
            meta["mode"] = "cli"
            meta_path.write_text(yaml.safe_dump(meta))
            print("Container started.")
            login_cmd = f"luskctl login {project.id} {task_id}"
            raw_cmd = f"podman exec -it {cname} bash"
            print(f"Login with: {_blue(login_cmd, color_enabled)}")
            print(f"  (or:      {_blue(raw_cmd, color_enabled)})")
            return

    env, volumes = build_task_env_and_volumes(project, task_id)

    # Prepare agent-config dir (subagents from project YAML, filtered by default/selected)
    subagents = list(project.agent_config.get("subagents") or [])
    agent_config_dir = prepare_agent_config_dir(project, task_id, subagents, agents)
    volumes.append(f"{agent_config_dir}:/home/dev/.luskctl:Z")

    # Run detached and keep the container alive so users can exec into it later
    # Note: We intentionally do NOT use --rm so containers persist after stopping.
    # This allows `task restart` to quickly resume stopped containers.
    cmd = ["podman", "run", "-d"]
    cmd += _podman_userns_args()
    cmd += gpu_run_args(project)
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
    stream_initial_logs(
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
    meta, meta_path = load_task_meta(project.id, task_id, "web")

    mode_updated = meta.get("mode") != "web"
    if mode_updated:
        meta["mode"] = "web"

    port = meta.get("web_port")
    port_updated = False
    if not isinstance(port, int):
        port = assign_web_port()
        meta["web_port"] = port
        port_updated = True

    env, volumes = build_task_env_and_volumes(project, task_id)

    # Prepare agent-config dir (subagents from project YAML, filtered by default/selected)
    subagents = list(project.agent_config.get("subagents") or [])
    agent_config_dir = prepare_agent_config_dir(project, task_id, subagents, agents)
    volumes.append(f"{agent_config_dir}:/home/dev/.luskctl:Z")

    env = apply_web_env_overrides(env, backend, project.default_agent)

    # Save the effective backend to task metadata for UI display
    effective_backend = env.get("LUSKUI_BACKEND", "codex")
    backend_updated = meta.get("backend") != effective_backend
    if backend_updated:
        meta["backend"] = effective_backend

    # Write metadata once if anything was updated
    if port_updated or backend_updated or mode_updated:
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
    cmd += gpu_run_args(project)
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
    # NOTE (#180): The headless command passes --dangerously-skip-permissions,
    # --add-dir /, --agents, and git env vars directly instead of relying on
    # the claude() bash wrapper function from luskctl-claude.sh.  This is
    # because `timeout` is an external command that exec's `claude` from
    # PATH — it bypasses bash functions entirely.  The wrapper is still used
    # for interactive sessions where the user types `claude` at the prompt.
    # Ideally the wrapper and headless paths should share a single source of
    # truth for these flags; see #180.
    cname = container_name(project.id, "run", task_id)

    # Agents flag: inject via env var to avoid brittle command substitution
    agents_flag = ""
    agents_json_path = agent_config_dir / "agents.json"
    if agents_json_path.exists():
        env["LUSKCTL_AGENTS_JSON"] = agents_json_path.read_text(encoding="utf-8").strip()
        agents_flag = ' --agents "$LUSKCTL_AGENTS_JSON"'

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
    cmd += gpu_run_args(project)
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
    meta, meta_path = load_task_meta(project.id, task_id)
    meta["status"] = "running"
    meta["mode"] = "run"
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


def task_restart(project_id: str, task_id: str, backend: str | None = None) -> None:
    """Restart a stopped task or re-run if the container is gone.

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
