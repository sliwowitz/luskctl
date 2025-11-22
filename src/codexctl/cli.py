#!/usr/bin/env python3
from __future__ import annotations

import argparse

from .lib import (
    generate_dockerfiles,
    build_images,
    config_root as _config_root,
    global_config_path as _global_config_path,
    global_config_search_paths as _global_config_search_paths,
    share_root as _share_root,
    state_root as _state_root,
    user_projects_root as _user_projects_root,
    build_root as _build_root,
    get_ui_base_port as _get_ui_base_port,
    task_new,
    task_list,
    task_run_cli,
    task_run_ui,
    list_projects,
)
import os
from importlib import resources
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="codexctl")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # projects
    sub.add_parser("projects", help="List all known projects")

    # config overview
    sub.add_parser("config", help="Show configuration, template and output paths")

    # generate
    p_gen = sub.add_parser("generate", help="Generate Dockerfiles for a project")
    p_gen.add_argument("project_id")

    # build
    p_build = sub.add_parser("build", help="Build images for a project")
    p_build.add_argument("project_id")

    # tasks
    p_task = sub.add_parser("task", help="Manage tasks")
    tsub = p_task.add_subparsers(dest="task_cmd", required=True)

    t_new = tsub.add_parser("new", help="Create a new task")
    t_new.add_argument("project_id")

    t_list = tsub.add_parser("list", help="List tasks")
    t_list.add_argument("project_id")

    t_run_cli = tsub.add_parser("run-cli", help="Run task in CLI (codex agent) mode")
    t_run_cli.add_argument("project_id")
    t_run_cli.add_argument("task_id")

    t_run_ui = tsub.add_parser("run-ui", help="Run task in UI (web) mode")
    t_run_ui.add_argument("project_id")
    t_run_ui.add_argument("task_id")

    args = parser.parse_args()

    if args.cmd == "generate":
        generate_dockerfiles(args.project_id)
    elif args.cmd == "build":
        build_images(args.project_id)
    elif args.cmd == "config":
        # READ PATHS
        print("Configuration (read):")
        gcfg = _global_config_path()
        print(f"- Global config file: {gcfg} (exists: {'yes' if Path(gcfg).is_file() else 'no'})")
        paths = _global_config_search_paths()
        if paths:
            print("- Global config search order:")
            for p in paths:
                exists = 'yes' if Path(p).is_file() else 'no'
                print(f"  • {p} (exists: {exists})")
        print(f"- UI base port: {_get_ui_base_port()}")

        uproj = _user_projects_root()
        sproj = _config_root()
        print(f"- User projects root: {uproj} (exists: {'yes' if Path(uproj).is_dir() else 'no'})")
        print(f"- System projects root: {sproj} (exists: {'yes' if Path(sproj).is_dir() else 'no'})")

        # Project configs discovered
        projs = list_projects()
        if projs:
            print("- Project configs:")
            for p in projs:
                print(f"  • {p.id}: {p.root / 'project.yml'}")
        else:
            print("- Project configs: none found")

        # Templates
        print("Templates (read):")
        tmpl_pkg = resources.files("codexctl") / "templates"
        try:
            names = [child.name for child in tmpl_pkg.iterdir() if child.name.endswith('.template')]
        except Exception:
            names = []
        print(f"- Package templates dir: {tmpl_pkg}")
        if names:
            for n in sorted(names):
                print(f"  • {n}")
        legacy = _share_root()
        print(f"- Legacy share dir (compat): {legacy}")

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
                for fname in ("L1.Dockerfile", "L2.Dockerfile", "L3.Dockerfile"):
                    path = base / fname
                    print(f"  • {p.id}: {path} (exists: {'yes' if path.is_file() else 'no'})")

        # ENVIRONMENT
        print("Environment overrides (if set):")
        for var in (
            "CODEXCTL_CONFIG_FILE",
            "CODEXCTL_CONFIG_DIR",
            "CODEXCTL_STATE_DIR",
            "CODEXCTL_SHARE_DIR",
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
            task_run_ui(args.project_id, args.task_id)
        else:
            parser.error("Unknown task subcommand")
    else:
        parser.error("Unknown command")


if __name__ == "__main__":
    main()
