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
from ..lib.git_gate import init_project_gate
from ..lib.projects import list_projects
from ..lib.ssh import init_project_ssh
from ..lib.tasks import (
    UI_BACKENDS,
    task_delete,
    task_list,
    task_new,
    task_run_cli,
    task_run_ui,
)
from ..lib.tasks import (
    get_tasks as _get_tasks,
)

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


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="codexctl",
        description="codexctl – generate/build images and run per-project task containers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Quick start (order of operations):\n"
            "- Online (HTTPS): generate → build → gate-init (optional) → task new → task run-*\n"
            "- Online (SSH):   generate → build → ssh-init → gate-init (recommended) → task new → task run-*\n"
            "- Gatekept:       generate → build → ssh-init → gate-init (required) →  task new → task run-*\n"
        ),
    )
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

    # gate-init
    p_gate = sub.add_parser(
        "gate-init",
        help=(
            "Initialize or update the host-side git gate for a project. "
            "For SSH upstreams this uses ONLY the project's ssh dir created by 'ssh-init' (not ~/.ssh)."
        ),
    )
    _a = p_gate.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except Exception:
        pass
    p_gate.add_argument("--force", action="store_true", help="Recreate the mirror from scratch")

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

    t_run_ui = tsub.add_parser("run-ui", help="Run task in UI (web) mode")
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
    known_backends = ", ".join(UI_BACKENDS)
    t_run_ui.add_argument(
        "--backend",
        dest="ui_backend",
        help=f"UI backend ({known_backends})",
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
        build_images(args.project_id, include_dev=getattr(args, "dev", False))
    elif args.cmd == "ssh-init":
        init_project_ssh(
            args.project_id,
            key_type=getattr(args, "key_type", "ed25519"),
            key_name=getattr(args, "key_name", None),
            force=getattr(args, "force", False),
        )
    elif args.cmd == "gate-init":
        res = init_project_gate(args.project_id, force=getattr(args, "force", False))
        print(
            f"Gate ready at {res['path']} (upstream: {res['upstream_url']}; created: {res['created']})"
        )
    elif args.cmd == "auth-codex":
        codex_auth(args.project_id)
    elif args.cmd == "auth-mistral":
        mistral_auth(args.project_id)
    elif args.cmd == "auth-claude":
        claude_auth(args.project_id)
    elif args.cmd == "auth-blablador":
        blablador_auth(args.project_id)
    elif args.cmd == "config":
        # READ PATHS
        print("Configuration (read):")
        gcfg = _global_config_path()
        print(f"- Global config file: {gcfg} (exists: {'yes' if Path(gcfg).is_file() else 'no'})")
        paths = _global_config_search_paths()
        if paths:
            print("- Global config search order:")
            for p in paths:
                exists = "yes" if Path(p).is_file() else "no"
                print(f"  • {p} (exists: {exists})")
        print(f"- UI base port: {_get_ui_base_port()}")

        # Envs base dir
        try:
            print(f"- Envs base dir (for mounts): {_get_envs_base_dir()}")
        except Exception:
            pass

        uproj = _user_projects_root()
        sproj = _config_root()
        print(f"- User projects root: {uproj} (exists: {'yes' if Path(uproj).is_dir() else 'no'})")
        print(
            f"- System projects root: {sproj} (exists: {'yes' if Path(sproj).is_dir() else 'no'})"
        )

        # Project configs discovered
        projs = list_projects()
        if projs:
            print("- Project configs:")
            for p in projs:
                print(f"  • {p.id}: {p.root / 'project.yml'}")
        else:
            print("- Project configs: none found")

        # Templates (package resources)
        print("Templates (read):")
        tmpl_pkg = resources.files("codexctl") / "resources" / "templates"
        try:
            names = [child.name for child in tmpl_pkg.iterdir() if child.name.endswith(".template")]
        except Exception:
            names = []
        print(f"- Package templates dir: {tmpl_pkg}")
        if names:
            for n in sorted(names):
                print(f"  • {n}")

        # Scripts (package resources)
        scr_pkg = resources.files("codexctl") / "resources" / "scripts"
        try:
            scr_names = [child.name for child in scr_pkg.iterdir() if child.is_file()]
        except Exception:
            scr_names = []
        print(f"Scripts (read):\n- Package scripts dir: {scr_pkg}")
        if scr_names:
            for n in sorted(scr_names):
                print(f"  • {n}")

        # WRITE PATHS
        print("Writable locations (write):")
        sroot = _state_root()
        print(f"- State root: {sroot} (exists: {'yes' if Path(sroot).is_dir() else 'no'})")
        build_root = _build_root()
        print(f"- Build root for generated files: {build_root}")
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
                    print(f"  • {p.id}: {path} (exists: {'yes' if path.is_file() else 'no'})")

        # ENVIRONMENT
        print("Environment overrides (if set):")
        for var in (
            "CODEXCTL_CONFIG_FILE",
            "CODEXCTL_CONFIG_DIR",
            "CODEXCTL_STATE_DIR",
            "CODEXCTL_RUNTIME_DIR",
            "XDG_DATA_HOME",
            "XDG_CONFIG_HOME",
        ):
            val = os.environ.get(var)
            if val is not None:
                print(f"- {var}={val}")
    elif args.cmd == "projects":
        projs = list_projects()
        if not projs:
            print("No projects found")
        else:
            print("Known projects:")
            for p in projs:
                upstream = p.upstream_url or "-"
                print(f"- {p.id} [{p.security_class}] upstream={upstream} config_root={p.root}")
    elif args.cmd == "task":
        if args.task_cmd == "new":
            task_new(args.project_id)
        elif args.task_cmd == "list":
            task_list(args.project_id)
        elif args.task_cmd == "run-cli":
            task_run_cli(args.project_id, args.task_id)
        elif args.task_cmd == "run-ui":
            task_run_ui(args.project_id, args.task_id, backend=getattr(args, "ui_backend", None))
        elif args.task_cmd == "delete":
            task_delete(args.project_id, args.task_id)
        else:
            parser.error("Unknown task subcommand")
    else:
        parser.error("Unknown command")


if __name__ == "__main__":
    main()
