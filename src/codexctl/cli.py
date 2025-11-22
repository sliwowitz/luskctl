#!/usr/bin/env python3
from __future__ import annotations

import argparse

from .lib import (
    generate_dockerfiles,
    build_images,
    task_new,
    task_list,
    task_run_cli,
    task_run_ui,
    list_projects,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="codexctl")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # projects
    sub.add_parser("projects", help="List all known projects")

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
