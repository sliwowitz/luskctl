#!/usr/bin/env python3
"""CLI entry point and argument parser for luskctl."""

import argparse
import os
from importlib import resources
from pathlib import Path

from ..lib.containers.task_runners import (
    task_restart,
    task_run_cli,
    task_run_headless,
    task_run_web,
)
from ..lib.containers.tasks import (
    get_tasks as _get_tasks,
    task_delete,
    task_list,
    task_login,
    task_logs,
    task_new,
    task_status,
    task_stop,
)
from ..lib.core.config import (
    build_root as _build_root,
    bundled_presets_dir as _bundled_presets_dir,
    config_root as _config_root,
    get_envs_base_dir as _get_envs_base_dir,
    get_logs_partial_streaming as _get_logs_partial_streaming,
    get_ui_base_port as _get_ui_base_port,
    global_config_path as _global_config_path,
    global_config_search_paths as _global_config_search_paths,
    global_presets_dir as _global_presets_dir,
    state_root as _state_root,
    user_projects_root as _user_projects_root,
)
from ..lib.core.projects import derive_project, list_presets, list_projects
from ..lib.core.version import format_version_string, get_version_info
from ..lib.facade import (
    AUTH_PROVIDERS,
    WEB_BACKENDS,
    authenticate,
    build_images,
    generate_dockerfiles,
    init_project_ssh,
    maybe_pause_for_ssh_key_registration,
    sync_project_gate,
)
from ..lib.wizards.new_project import run_wizard
from ..ui_utils.terminal import (
    gray as _gray,
    supports_color as _supports_color,
    violet as _violet,
    yes_no as _yes_no,
)

# Optional: bash completion via argcomplete
try:
    import argcomplete  # type: ignore
except ImportError:  # pragma: no cover - optional dep
    argcomplete = None  # type: ignore


def _complete_project_ids(
    prefix: str, parsed_args, **kwargs
):  # pragma: no cover - shell integration
    """Return project IDs matching *prefix* for argcomplete."""
    try:
        ids = [p.id for p in list_projects()]
    except Exception:
        return []
    if prefix:
        ids = [i for i in ids if str(i).startswith(prefix)]
    return ids


def _complete_task_ids(prefix: str, parsed_args, **kwargs):  # pragma: no cover - shell integration
    """Return task IDs matching *prefix* for argcomplete."""
    project_id = getattr(parsed_args, "project_id", None)
    if not project_id:
        return []
    try:
        tids = [str(t.get("task_id", "")) for t in _get_tasks(project_id) if t.get("task_id")]
    except Exception:
        return []
    if prefix:
        tids = [t for t in tids if t.startswith(prefix)]
    return tids


def _cmd_config_show(project_id: str, preset: str | None) -> None:
    """Show resolved agent config with provenance annotations."""
    import json

    from ..lib.containers.agent_config import build_agent_config_stack

    color_enabled = _supports_color()

    stack = build_agent_config_stack(project_id, preset=preset)
    resolved = stack.resolve()
    scopes = stack.scopes

    # Print provenance per level
    if not scopes and not resolved:
        print(f"No agent config defined for project '{project_id}'")
        return

    print(f"Resolved agent config for '{project_id}':")
    if preset:
        print(f"  (with preset: {preset})")
    print()

    for scope in scopes:
        keys = ", ".join(sorted(scope.data.keys()))
        print(f"  [{_gray(scope.level, color_enabled)}] keys: {keys}")

    print()
    print(json.dumps(resolved, indent=2, default=str))


def _cmd_project_init(project_id: str) -> None:
    """Full project setup: ssh-init, generate, build, gate-sync."""
    print("==> Initializing SSH...")
    init_project_ssh(project_id)
    maybe_pause_for_ssh_key_registration(project_id)

    print("==> Generating Dockerfiles...")
    generate_dockerfiles(project_id)

    print("==> Building images...")
    build_images(project_id)

    print("==> Syncing git gate...")
    res = sync_project_gate(project_id)
    if not res["success"]:
        raise SystemExit(f"Gate sync failed: {', '.join(res['errors'])}")
    print(f"Gate ready at {res['path']}")


def _print_config() -> None:
    """Display all configuration, template and output paths."""
    color_enabled = _supports_color()
    # READ PATHS
    print("Configuration (read):")
    gcfg = _global_config_path()
    gcfg_exists = Path(gcfg).is_file()
    print(
        f"- Global config file: {_gray(str(gcfg), color_enabled)} "
        f"(exists: {_yes_no(gcfg_exists, color_enabled)})"
    )
    paths = _global_config_search_paths()
    if paths:
        print("- Global config search order:")
        for p in paths:
            exists = Path(p).is_file()
            print(f"  • {_gray(str(p), color_enabled)} (exists: {_yes_no(exists, color_enabled)})")
    print(f"- Web base port: {_get_ui_base_port()}")

    # Envs base dir
    try:
        print(f"- Envs base dir (for mounts): {_gray(str(_get_envs_base_dir()), color_enabled)}")
    except OSError as e:
        print(f"- Envs base dir (for mounts): error: {e}")

    uproj = _user_projects_root()
    sproj = _config_root()
    uproj_exists = Path(uproj).is_dir()
    print(
        f"- User projects root: {_gray(str(uproj), color_enabled)} "
        f"(exists: {_yes_no(uproj_exists, color_enabled)})"
    )
    print(
        f"- System projects root: {_gray(str(sproj), color_enabled)} "
        f"(exists: {_yes_no(Path(sproj).is_dir(), color_enabled)})"
    )
    gpresets = _global_presets_dir()
    print(
        f"- Global presets dir: {_gray(str(gpresets), color_enabled)} "
        f"(exists: {_yes_no(Path(gpresets).is_dir(), color_enabled)})"
    )
    bpresets = _bundled_presets_dir()
    bpresets_names: list[str] = []
    try:
        bpresets_names = sorted(
            p.stem for p in bpresets.iterdir() if p.is_file() and p.suffix in (".yml", ".yaml")
        )
    except FileNotFoundError:
        pass  # Directory may not exist in some installations
    except OSError as e:
        print(f"  Warning: could not list bundled presets: {e}")
    print(f"- Bundled presets: {_gray(str(bpresets), color_enabled)}")
    if bpresets_names:
        for n in bpresets_names:
            print(f"  • {n}")

    # Project configs discovered
    projs = list_projects()
    if projs:
        print("- Project configs:")
        for p in projs:
            print(
                f"  • {_violet(str(p.id), color_enabled)}: "
                f"{_gray(str(p.root / 'project.yml'), color_enabled)}"
            )
    else:
        print("- Project configs: none found")

    # Templates (package resources)
    print("Templates (read):")
    tmpl_pkg = resources.files("luskctl") / "resources" / "templates"
    try:
        names = [child.name for child in tmpl_pkg.iterdir() if child.name.endswith(".template")]
    except FileNotFoundError:
        names = []
    except OSError as e:
        names = []
        print(f"  Warning: could not list templates: {e}")
    print(f"- Package templates dir: {_gray(str(tmpl_pkg), color_enabled)}")
    if names:
        for n in sorted(names):
            print(f"  • {_gray(str(n), color_enabled)}")

    # Scripts (package resources)
    scr_pkg = resources.files("luskctl") / "resources" / "scripts"
    try:
        scr_names = [child.name for child in scr_pkg.iterdir() if child.is_file()]
    except FileNotFoundError:
        scr_names = []
    except OSError as e:
        scr_names = []
        print(f"  Warning: could not list scripts: {e}")
    print(f"Scripts (read):\n- Package scripts dir: {_gray(str(scr_pkg), color_enabled)}")
    if scr_names:
        for n in sorted(scr_names):
            print(f"  • {_gray(str(n), color_enabled)}")

    # WRITE PATHS
    print("Writable locations (write):")
    sroot = _state_root()
    sroot_exists = Path(sroot).is_dir()
    print(
        f"- State root: {_gray(str(sroot), color_enabled)} "
        f"(exists: {_yes_no(sroot_exists, color_enabled)})"
    )
    build_root = _build_root()
    print(f"- Build root for generated files: {_gray(str(build_root), color_enabled)}")
    if projs:
        print("- Expected generated files per project:")
        for p in projs:
            base = build_root / p.id
            for fname in (
                "L0.Dockerfile",
                "L1.cli.Dockerfile",
                "L1.ui.Dockerfile",
                "L2.Dockerfile",
            ):
                path = base / fname
                print(
                    f"  • {_violet(str(p.id), color_enabled)}: "
                    f"{_gray(str(path), color_enabled)} "
                    f"(exists: {_yes_no(path.is_file(), color_enabled)})"
                )

    # Native Claude configuration locations
    home = Path.home()
    claude_agents_dir = home / ".claude" / "agents"
    claude_settings = home / ".claude" / "settings.json"
    print("Native Claude configuration (edit with your OS tools):")
    print(
        f"- Global agents dir: {_gray(str(claude_agents_dir), color_enabled)} "
        f"(exists: {_yes_no(claude_agents_dir.is_dir(), color_enabled)})"
    )
    print(
        f"- Global settings: {_gray(str(claude_settings), color_enabled)} "
        f"(exists: {_yes_no(claude_settings.is_file(), color_enabled)})"
    )
    print("  (MCPs go in settings.json under mcpServers)")

    # ENVIRONMENT
    print("Environment overrides (if set):")
    for var in (
        "LUSKCTL_CONFIG_FILE",
        "LUSKCTL_CONFIG_DIR",
        "LUSKCTL_STATE_DIR",
        "LUSKCTL_RUNTIME_DIR",
        "XDG_DATA_HOME",
        "XDG_CONFIG_HOME",
    ):
        val = os.environ.get(var)
        if val is not None:
            print(f"- {var}={_gray(val, color_enabled)}")


def main() -> None:
    """Parse CLI arguments and dispatch to the appropriate command handler."""
    # Get version info for --version flag
    version, branch = get_version_info()
    version_string = format_version_string(version, branch)

    parser = argparse.ArgumentParser(
        prog="luskctl",
        description="luskctl – generate/build images and run per-project task containers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Quick start:\n"
            "  1. Setup:  luskctl project-init <project_id>\n"
            "  2. Work:   luskctl task start <project_id>         (new CLI task)\n"
            "             luskctl task start <project_id> --web   (new web task)\n"
            "  3. Login:  luskctl login <project_id> <task_id>\n"
            "\n"
            "Step-by-step (order of operations):\n"
            "  Online (HTTPS): generate → build → gate-sync (optional) → task new → task run-*\n"
            "  Online (SSH):   generate → build → ssh-init → gate-sync (recommended) → task new → task run-*\n"
            "  Gatekeeping:    generate → build → ssh-init → gate-sync (required) → task new → task run-*\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"luskctl {version_string}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # projects
    sub.add_parser("projects", help="List all known projects")

    # config overview
    sub.add_parser("config", help="Show configuration, template and output paths")

    # config-show (resolved agent config with provenance)
    p_config_show = sub.add_parser(
        "config-show",
        help="Show resolved agent config for a project (with provenance per level)",
    )
    _a = p_config_show.add_argument("project_id", help="Project ID")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    p_config_show.add_argument("--preset", help="Apply a preset before showing resolved config")

    # presets
    p_presets = sub.add_parser("presets", help="Manage agent config presets")
    presets_sub = p_presets.add_subparsers(dest="presets_cmd", required=True)
    p_presets_list = presets_sub.add_parser("list", help="List available presets for a project")
    _a = p_presets_list.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass

    # generate
    p_gen = sub.add_parser("generate", help="Generate Dockerfiles for a project")
    _a = p_gen.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass

    # build
    p_build = sub.add_parser("build", help="Build images for a project")
    _a = p_build.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    p_build.add_argument(
        "--agents",
        action="store_true",
        help="Rebuild L0+L1+L2 with fresh agent installs (codex, claude, opencode, vibe)",
    )
    p_build.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Full rebuild with no cache (includes base image pull and apt packages)",
    )
    p_build.add_argument(
        "--dev",
        action="store_true",
        help="Also build a manual dev image from L0 (tagged as <project>:l2-dev)",
    )

    # ssh-init
    p_ssh = sub.add_parser(
        "ssh-init", help="Initialize shared SSH dir and generate a keypair for a project"
    )
    _a = p_ssh.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    p_ssh.add_argument(
        "--key-type",
        choices=["ed25519", "rsa"],
        default="ed25519",
        help="Key algorithm (default: ed25519)",
    )
    p_ssh.add_argument(
        "--key-name",
        default=None,
        help="Key file name (without .pub). Default: id_<type>_<project>",
    )
    p_ssh.add_argument("--force", action="store_true", help="Overwrite existing key and config")

    # gate-sync
    p_gate = sub.add_parser(
        "gate-sync",
        help=(
            "Sync the host-side git gate for a project (creates it if missing). "
            "For SSH upstreams this uses ONLY the project's ssh dir created by 'ssh-init' (not ~/.ssh)."
        ),
    )
    _a = p_gate.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    p_gate.add_argument(
        "--force-reinit",
        dest="force_reinit",
        action="store_true",
        help="Recreate the mirror from scratch",
    )

    # project-init
    p_pinit = sub.add_parser(
        "project-init",
        help="Full project setup: ssh-init + generate + build + gate-sync",
    )
    _a = p_pinit.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass

    # project-wizard
    sub.add_parser(
        "project-wizard",
        help="Interactive wizard to create a new project configuration",
    )

    # project-derive
    p_derive = sub.add_parser(
        "project-derive",
        help="Create a new project derived from an existing one (shared infra, fresh agent config)",
    )
    _a = p_derive.add_argument("source_id", help="Source project ID to derive from")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    p_derive.add_argument("new_id", help="New project ID")

    # auth <provider> <project_id>
    provider_names = list(AUTH_PROVIDERS)
    providers_help = ", ".join(f"{p.name} ({p.label})" for p in AUTH_PROVIDERS.values())
    p_auth = sub.add_parser(
        "auth",
        help="Authenticate an agent/tool for a project",
        description=f"Available providers: {providers_help}",
    )
    p_auth.add_argument("provider", choices=provider_names, metavar="provider")
    _a = p_auth.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass

    # login (top-level shortcut)
    p_login = sub.add_parser("login", help="Open interactive shell in a running task container")
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

    # run-claude (headless autopilot)
    p_run_claude = sub.add_parser(
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

    # tasks
    p_task = sub.add_parser("task", help="Manage tasks")
    tsub = p_task.add_subparsers(dest="task_cmd", required=True)

    t_new = tsub.add_parser("new", help="Create a new task")
    _a = t_new.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass

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
    t_restart.add_argument(
        "--backend",
        choices=["gradio", "streamlit"],
        help="Backend to use when re-running a web task (default: use saved backend)",
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

    # Enable bash completion if argcomplete is present and activated
    if argcomplete is not None:  # pragma: no cover - shell integration
        try:
            argcomplete.autocomplete(parser)  # type: ignore[attr-defined]
        except (TypeError, AttributeError):
            pass

    args = parser.parse_args()

    if args.cmd == "generate":
        generate_dockerfiles(args.project_id)
    elif args.cmd == "build":
        build_images(
            args.project_id,
            include_dev=getattr(args, "dev", False),
            rebuild_agents=getattr(args, "agents", False),
            full_rebuild=getattr(args, "full_rebuild", False),
        )
    elif args.cmd == "ssh-init":
        init_project_ssh(
            args.project_id,
            key_type=getattr(args, "key_type", "ed25519"),
            key_name=getattr(args, "key_name", None),
            force=getattr(args, "force", False),
        )
    elif args.cmd == "gate-sync":
        res = sync_project_gate(
            args.project_id,
            force_reinit=getattr(args, "force_reinit", False),
        )
        if not res["success"]:
            raise SystemExit(f"Gate sync failed: {', '.join(res['errors'])}")
        print(
            f"Gate ready at {res['path']} (upstream: {res['upstream_url']}; created: {res['created']})"
        )
    elif args.cmd == "project-init":
        _cmd_project_init(args.project_id)
    elif args.cmd == "project-derive":
        target = derive_project(args.source_id, args.new_id)
        print(f"Derived project '{args.new_id}' from '{args.source_id}' at {target}")
        print("Next steps:")
        print(f"  1. Edit {target / 'project.yml'} (customize agent: section)")
        print(f"  2. Initialize: luskctl project-init {args.new_id}")
        print("  Tip: global presets are shared across projects (see luskctl config)")
    elif args.cmd == "project-wizard":
        run_wizard(init_fn=_cmd_project_init)
    elif args.cmd == "auth":
        authenticate(args.project_id, args.provider)
    elif args.cmd == "config":
        _print_config()
    elif args.cmd == "config-show":
        _cmd_config_show(args.project_id, getattr(args, "preset", None))
    elif args.cmd == "presets":
        if args.presets_cmd == "list":
            presets = list_presets(args.project_id)
            if not presets:
                print(f"No presets found for project '{args.project_id}'")
            else:
                print(f"Presets for '{args.project_id}':")
                for info in presets:
                    print(f"  - {info.name} ({info.source})")
    elif args.cmd == "projects":
        projs = list_projects()
        if not projs:
            print("No projects found")
        else:
            print("Known projects:")
            for p in projs:
                upstream = p.upstream_url or "-"
                print(f"- {p.id} [{p.security_class}] upstream={upstream} config_root={p.root}")
    elif args.cmd == "login":
        task_login(args.project_id, args.task_id)
    elif args.cmd == "run-claude":
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
        )
    elif args.cmd == "task":
        if args.task_cmd == "new":
            task_new(args.project_id)
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
            from ..lib.containers.task_runners import task_followup_headless

            task_followup_headless(
                args.project_id,
                args.task_id,
                args.prompt,
                follow=not getattr(args, "no_follow", False),
            )
        elif args.task_cmd == "start":
            task_id = task_new(args.project_id)
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
            parser.error("Unknown task subcommand")
    else:
        parser.error("Unknown command")


if __name__ == "__main__":
    main()
