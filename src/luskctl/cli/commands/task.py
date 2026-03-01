"""Task management commands: new, list, run-cli, run-web, start, etc."""

from ...lib.core.config import get_logs_partial_streaming as _get_logs_partial_streaming
from ...lib.core.projects import list_projects
from ...lib.facade import (
    WEB_BACKENDS,
    get_tasks as _get_tasks,
    task_delete,
    task_followup_headless,
    task_list,
    task_login,
    task_logs,
    task_new,
    task_rename,
    task_restart,
    task_run_cli,
    task_run_headless,
    task_run_web,
    task_status,
    task_stop,
)


def _complete_project_ids(prefix, parsed_args, **kwargs):  # pragma: no cover
    """Return project IDs matching *prefix* for argcomplete."""
    try:
        ids = [p.id for p in list_projects()]
    except Exception:
        return []
    if prefix:
        ids = [i for i in ids if str(i).startswith(prefix)]
    return ids


def _complete_task_ids(prefix, parsed_args, **kwargs):  # pragma: no cover
    """Return task IDs matching *prefix* for argcomplete."""
    project_id = getattr(parsed_args, "project_id", None)
    if not project_id:
        return []
    try:
        tids = [t.task_id for t in _get_tasks(project_id) if t.task_id]
    except Exception:
        return []
    if prefix:
        tids = [t for t in tids if t.startswith(prefix)]
    return tids


def register(subparsers) -> None:
    """Register task-related subcommands."""
    # login (top-level shortcut)
    p_login = subparsers.add_parser("login", help="Open interactive shell in a running container")
    _a = p_login.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    _a = p_login.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass

    # run-claude (headless autopilot, top-level shortcut)
    p_run_claude = subparsers.add_parser(
        "run-claude", help="Run Claude headlessly in a new task (autopilot mode)"
    )
    _a = p_run_claude.add_argument("project_id", help="Project ID")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    p_run_claude.add_argument("prompt", help="Task prompt for Claude")
    p_run_claude.add_argument(
        "--config", dest="agent_config", help="Path to agent config YAML file"
    )
    p_run_claude.add_argument(
        "--preset", help="Name of a preset to apply (global or project-level)"
    )
    p_run_claude.add_argument("--model", help="Model override (sonnet, opus, haiku)")
    p_run_claude.add_argument("--max-turns", type=int, help="Maximum agent turns")
    p_run_claude.add_argument("--timeout", type=int, help="Maximum runtime in seconds")
    p_run_claude.add_argument(
        "--no-follow",
        action="store_true",
        help="Detach after starting (don't stream output)",
    )
    p_run_claude.add_argument(
        "--agent",
        dest="selected_agents",
        action="append",
        default=None,
        help="Include a non-default agent by name (repeatable)",
    )
    p_run_claude.add_argument(
        "--name", help="Human-readable task name (slug-style, e.g. fix-auth-bug)"
    )

    # task subcommand group
    p_task = subparsers.add_parser("task", help="Manage tasks")
    tsub = p_task.add_subparsers(dest="task_cmd", required=True)

    t_new = tsub.add_parser("new", help="Create a new task")
    _a = t_new.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    t_new.add_argument("--name", help="Human-readable task name (slug-style, e.g. fix-auth-bug)")

    t_list = tsub.add_parser("list", help="List tasks")
    _a = t_list.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    t_list.add_argument(
        "--status",
        dest="filter_status",
        help="Filter by task status (e.g. running, stopped, created)",
    )
    t_list.add_argument(
        "--mode",
        dest="filter_mode",
        help="Filter by task mode (e.g. cli, web, run)",
    )
    t_list.add_argument(
        "--agent",
        dest="filter_agent",
        help="Filter by agent preset name",
    )

    t_run_cli = tsub.add_parser("run-cli", help="Run task in CLI (codex agent) mode")
    _a = t_run_cli.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    _a = t_run_cli.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    t_run_cli.add_argument(
        "--agent",
        dest="selected_agents",
        action="append",
        default=None,
        help="Include a non-default agent by name (repeatable)",
    )
    t_run_cli.add_argument("--preset", help="Name of a preset to apply (global or project-level)")

    t_run_ui = tsub.add_parser("run-web", help="Run task in web mode")
    _a = t_run_ui.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    _a = t_run_ui.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    known_backends = ", ".join(WEB_BACKENDS)
    t_run_ui.add_argument(
        "--backend",
        dest="ui_backend",
        help=f"Web backend ({known_backends})",
    )
    t_run_ui.add_argument(
        "--agent",
        dest="selected_agents",
        action="append",
        default=None,
        help="Include a non-default agent by name (repeatable)",
    )
    t_run_ui.add_argument("--preset", help="Name of a preset to apply (global or project-level)")

    t_delete = tsub.add_parser("delete", help="Delete a task and its containers")
    _a = t_delete.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    _a = t_delete.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass

    t_stop = tsub.add_parser("stop", help="Gracefully stop a running task container")
    _a = t_stop.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    _a = t_stop.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    t_stop.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Seconds before SIGKILL (overrides project run.shutdown_timeout, default 10)",
    )

    t_restart = tsub.add_parser("restart", help="Restart a stopped task or re-run if gone")
    _a = t_restart.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    _a = t_restart.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    restart_backends = ", ".join(WEB_BACKENDS)
    t_restart.add_argument(
        "--backend",
        choices=list(WEB_BACKENDS),
        help=f"Backend to use when re-running a web task ({restart_backends}; default: use saved backend)",
    )

    t_followup = tsub.add_parser(
        "followup", help="Follow up on a completed/failed headless task with a new prompt"
    )
    _a = t_followup.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    _a = t_followup.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    t_followup.add_argument("-p", "--prompt", required=True, help="Follow-up prompt for Claude")
    t_followup.add_argument(
        "--no-follow",
        action="store_true",
        help="Detach after starting (don't stream output)",
    )

    t_start = tsub.add_parser(
        "start",
        help="Create a new task and immediately run it (default: CLI mode)",
    )
    _a = t_start.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    t_start.add_argument(
        "--web",
        action="store_true",
        help="Start in web mode instead of CLI",
    )
    t_start.add_argument(
        "--backend",
        help="Web backend (default from project config or 'codex')",
    )
    t_start.add_argument(
        "--agent",
        dest="selected_agents",
        action="append",
        default=None,
        help="Include a non-default agent by name (repeatable)",
    )
    t_start.add_argument("--preset", help="Name of a preset to apply (global or project-level)")
    t_start.add_argument("--name", help="Human-readable task name (slug-style, e.g. fix-auth-bug)")

    t_rename = tsub.add_parser("rename", help="Rename a task")
    _a = t_rename.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    _a = t_rename.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    t_rename.add_argument("name", help="New task name (slug-style, e.g. fix-auth-bug)")

    t_status = tsub.add_parser("status", help="Show actual container state vs metadata")
    _a = t_status.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    _a = t_status.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass

    t_logs = tsub.add_parser("logs", help="View formatted container logs for a task")
    _a = t_logs.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    _a = t_logs.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    t_logs.add_argument("-f", "--follow", action="store_true", help="Follow live output")
    t_logs.add_argument(
        "--raw", action="store_true", help="Show raw podman output (bypass formatting)"
    )
    t_logs.add_argument("--tail", type=int, default=None, help="Show only the last N lines")
    stream_group = t_logs.add_mutually_exclusive_group()
    stream_group.add_argument(
        "--stream",
        action="store_true",
        default=None,
        help="Enable partial streaming (typewriter effect, default)",
    )
    stream_group.add_argument(
        "--no-stream",
        action="store_true",
        default=None,
        help="Disable partial streaming (show coalesced messages only)",
    )


def dispatch(args) -> bool:
    """Handle task-related commands.  Returns True if handled."""
    if args.cmd == "login":
        task_login(args.project_id, args.task_id)
        return True
    if args.cmd == "run-claude":
        task_run_headless(
            args.project_id,
            args.prompt,
            config_path=getattr(args, "agent_config", None),
            model=getattr(args, "model", None),
            max_turns=getattr(args, "max_turns", None),
            timeout=getattr(args, "timeout", None),
            follow=not getattr(args, "no_follow", False),
            agents=getattr(args, "selected_agents", None),
            preset=getattr(args, "preset", None),
            name=getattr(args, "name", None),
        )
        return True
    if args.cmd == "task":
        return _dispatch_task_sub(args)
    return False


def _dispatch_task_sub(args) -> bool:
    """Dispatch ``task <subcommand>`` to the right handler."""
    if args.task_cmd == "new":
        task_new(args.project_id, name=getattr(args, "name", None))
    elif args.task_cmd == "list":
        task_list(
            args.project_id,
            status=getattr(args, "filter_status", None),
            mode=getattr(args, "filter_mode", None),
            agent=getattr(args, "filter_agent", None),
        )
    elif args.task_cmd == "run-cli":
        task_run_cli(
            args.project_id,
            args.task_id,
            agents=getattr(args, "selected_agents", None),
            preset=getattr(args, "preset", None),
        )
    elif args.task_cmd == "run-web":
        task_run_web(
            args.project_id,
            args.task_id,
            backend=getattr(args, "ui_backend", None),
            agents=getattr(args, "selected_agents", None),
            preset=getattr(args, "preset", None),
        )
    elif args.task_cmd == "delete":
        task_delete(args.project_id, args.task_id)
    elif args.task_cmd == "stop":
        task_stop(args.project_id, args.task_id, timeout=getattr(args, "timeout", None))
    elif args.task_cmd == "restart":
        backend = getattr(args, "backend", None)
        task_restart(args.project_id, args.task_id, backend=backend)
    elif args.task_cmd == "followup":
        task_followup_headless(
            args.project_id,
            args.task_id,
            args.prompt,
            follow=not getattr(args, "no_follow", False),
        )
    elif args.task_cmd == "start":
        task_id = task_new(args.project_id, name=getattr(args, "name", None))
        selected = getattr(args, "selected_agents", None)
        preset = getattr(args, "preset", None)
        if args.web:
            task_run_web(
                args.project_id,
                task_id,
                backend=getattr(args, "backend", None),
                agents=selected,
                preset=preset,
            )
        else:
            task_run_cli(args.project_id, task_id, agents=selected, preset=preset)
    elif args.task_cmd == "rename":
        task_rename(args.project_id, args.task_id, args.name)
    elif args.task_cmd == "status":
        task_status(args.project_id, args.task_id)
    elif args.task_cmd == "logs":
        # Resolve streaming: CLI flag → config → default (True)
        if getattr(args, "no_stream", None):
            stream = False
        elif getattr(args, "stream", None):
            stream = True
        else:
            stream = _get_logs_partial_streaming()
        task_logs(
            args.project_id,
            args.task_id,
            follow=getattr(args, "follow", False),
            raw=getattr(args, "raw", False),
            tail=getattr(args, "tail", None),
            streaming=stream,
        )
    else:
        return False
    return True
