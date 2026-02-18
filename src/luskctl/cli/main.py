#!/usr/bin/env python3

import argparse
import os
from importlib import resources
from pathlib import Path

from ..lib.auth import blablador_auth, claude_auth, codex_auth, mistral_auth
from ..lib.config import (
    build_root as _build_root,
)
from ..lib.config import (
    config_root as _config_root,
)
from ..lib.config import (
    get_envs_base_dir as _get_envs_base_dir,
)
from ..lib.config import (
    get_ui_base_port as _get_ui_base_port,
)
from ..lib.config import (
    global_config_path as _global_config_path,
)
from ..lib.config import (
    global_config_search_paths as _global_config_search_paths,
)
from ..lib.config import (
    state_root as _state_root,
)
from ..lib.config import (
    user_projects_root as _user_projects_root,
)
from ..lib.docker import build_images, generate_dockerfiles
from ..lib.git_gate import sync_project_gate
from ..lib.projects import list_projects
from ..lib.ssh import init_project_ssh
from ..lib.task_env import WEB_BACKENDS
from ..lib.tasks import (
    get_tasks as _get_tasks,
)
from ..lib.tasks import (
    task_delete,
    task_list,
    task_login,
    task_new,
    task_restart,
    task_run_cli,
    task_run_web,
    task_status,
    task_stop,
)
from ..lib.terminal import gray as _gray
from ..lib.terminal import supports_color as _supports_color
from ..lib.terminal import violet as _violet
from ..lib.terminal import yes_no as _yes_no
from ..lib.version import format_version_string, get_version_info

# Optional: bash completion via argcomplete
try:
    import argcomplete  # type: ignore
except Exception:  # pragma: no cover - optional dep
    argcomplete = None  # type: ignore


def _complete_project_ids(
    prefix: str, parsed_args, **kwargs
):  # pragma: no cover - shell integration
    try:
        ids = [p.id for p in list_projects()]
    except Exception:
        return []
    if prefix:
        ids = [i for i in ids if str(i).startswith(prefix)]
    return ids


def _complete_task_ids(prefix: str, parsed_args, **kwargs):  # pragma: no cover - shell integration
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


def _cmd_project_init(project_id: str) -> None:
    """Full project setup: ssh-init, generate, build, gate-sync."""
    print("==> Initializing SSH...")
    init_project_ssh(project_id)

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
    except Exception:
        pass

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
    except Exception:
        names = []
    print(f"- Package templates dir: {_gray(str(tmpl_pkg), color_enabled)}")
    if names:
        for n in sorted(names):
            print(f"  • {_gray(str(n), color_enabled)}")

    # Scripts (package resources)
    scr_pkg = resources.files("luskctl") / "resources" / "scripts"
    try:
        scr_names = [child.name for child in scr_pkg.iterdir() if child.is_file()]
    except Exception:
        scr_names = []
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

    # generate
    p_gen = sub.add_parser("generate", help="Generate Dockerfiles for a project")
    _a = p_gen.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass

    # build
    p_build = sub.add_parser("build", help="Build images for a project")
    _a = p_build.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
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
    except Exception:
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
    except Exception:
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
    except Exception:
        pass

    # auth-codex
    p_auth_codex = sub.add_parser(
        "auth-codex",
        help="Authenticate Codex CLI by running 'codex login' inside an L2 CLI container with port forwarding",
    )
    _a = p_auth_codex.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass

    # auth-mistral
    p_auth_mistral = sub.add_parser(
        "auth-mistral",
        help="Set up Mistral API key for Vibe CLI inside an L2 CLI container",
    )
    _a = p_auth_mistral.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass

    # auth-claude
    p_auth_claude = sub.add_parser(
        "auth-claude",
        help="Set up Claude API key for CLI inside an L2 CLI container",
    )
    _a = p_auth_claude.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass

    # auth-blablador
    p_auth_blablador = sub.add_parser(
        "auth-blablador",
        help="Set up Blablador API key for OpenCode inside an L2 CLI container",
    )
    _a = p_auth_blablador.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass

    # login (top-level shortcut)
    p_login = sub.add_parser("login", help="Open interactive shell in a running task container")
    _a = p_login.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass
    _a = p_login.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except Exception:
        pass

    # tasks
    p_task = sub.add_parser("task", help="Manage tasks")
    tsub = p_task.add_subparsers(dest="task_cmd", required=True)

    t_new = tsub.add_parser("new", help="Create a new task")
    _a = t_new.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass

    t_list = tsub.add_parser("list", help="List tasks")
    _a = t_list.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass

    t_run_cli = tsub.add_parser("run-cli", help="Run task in CLI (codex agent) mode")
    _a = t_run_cli.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass
    _a = t_run_cli.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except Exception:
        pass

    t_run_ui = tsub.add_parser("run-web", help="Run task in web mode")
    _a = t_run_ui.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass
    _a = t_run_ui.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except Exception:
        pass
    known_backends = ", ".join(WEB_BACKENDS)
    t_run_ui.add_argument(
        "--backend",
        dest="ui_backend",
        help=f"Web backend ({known_backends})",
    )

    t_delete = tsub.add_parser("delete", help="Delete a task and its containers")
    _a = t_delete.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass
    _a = t_delete.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except Exception:
        pass

    t_stop = tsub.add_parser("stop", help="Gracefully stop a running task container")
    _a = t_stop.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass  # argcomplete not available or completer attribute not supported
    _a = t_stop.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except Exception:
        pass  # argcomplete not available or completer attribute not supported

    t_restart = tsub.add_parser("restart", help="Restart a stopped task or re-run if gone")
    _a = t_restart.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass  # argcomplete not available or completer attribute not supported
    _a = t_restart.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except Exception:
        pass  # argcomplete not available or completer attribute not supported
    t_restart.add_argument(
        "--backend",
        choices=["gradio", "streamlit"],
        help="Backend to use when re-running a web task (default: use saved backend)",
    )

    t_start = tsub.add_parser(
        "start",
        help="Create a new task and immediately run it (default: CLI mode)",
    )
    _a = t_start.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass  # argcomplete not available or completer attribute not supported
    t_start.add_argument(
        "--web",
        action="store_true",
        help="Start in web mode instead of CLI",
    )
    t_start.add_argument(
        "--backend",
        help="Web backend (default from project config or 'codex')",
    )

    t_status = tsub.add_parser("status", help="Show actual container state vs metadata")
    _a = t_status.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass  # argcomplete not available or completer attribute not supported
    _a = t_status.add_argument("task_id")
    try:
        _a.completer = _complete_task_ids  # type: ignore[attr-defined]
    except Exception:
        pass  # argcomplete not available or completer attribute not supported

    # Enable bash completion if argcomplete is present and activated
    if argcomplete is not None:  # pragma: no cover - shell integration
        try:
            argcomplete.autocomplete(parser)  # type: ignore[attr-defined]
        except Exception:
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
    elif args.cmd == "auth-codex":
        codex_auth(args.project_id)
    elif args.cmd == "auth-mistral":
        mistral_auth(args.project_id)
    elif args.cmd == "auth-claude":
        claude_auth(args.project_id)
    elif args.cmd == "auth-blablador":
        blablador_auth(args.project_id)
    elif args.cmd == "config":
        _print_config()
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
    elif args.cmd == "task":
        if args.task_cmd == "new":
            task_new(args.project_id)
        elif args.task_cmd == "list":
            task_list(args.project_id)
        elif args.task_cmd == "run-cli":
            task_run_cli(args.project_id, args.task_id)
        elif args.task_cmd == "run-web":
            task_run_web(args.project_id, args.task_id, backend=getattr(args, "ui_backend", None))
        elif args.task_cmd == "delete":
            task_delete(args.project_id, args.task_id)
        elif args.task_cmd == "stop":
            task_stop(args.project_id, args.task_id)
        elif args.task_cmd == "restart":
            backend = getattr(args, "backend", None)
            task_restart(args.project_id, args.task_id, backend=backend)
        elif args.task_cmd == "start":
            task_id = task_new(args.project_id)
            if args.web:
                task_run_web(args.project_id, task_id, backend=getattr(args, "backend", None))
            else:
                task_run_cli(args.project_id, task_id)
        elif args.task_cmd == "status":
            task_status(args.project_id, args.task_id)
        else:
            parser.error("Unknown task subcommand")
    else:
        parser.error("Unknown command")


if __name__ == "__main__":
    main()
