"""Project management commands: list, derive, wizard, presets."""

from ...lib.core.projects import derive_project, list_presets, list_projects
from ...lib.wizards.new_project import run_wizard
from .setup import cmd_project_init


def _complete_project_ids(prefix, parsed_args, **kwargs):  # pragma: no cover
    """Return project IDs matching *prefix* for argcomplete."""
    try:
        ids = [p.id for p in list_projects()]
    except Exception:
        return []
    if prefix:
        ids = [i for i in ids if str(i).startswith(prefix)]
    return ids


def register(subparsers) -> None:
    """Register project management subcommands."""
    # projects
    subparsers.add_parser("projects", help="List all known projects")

    # project-wizard
    subparsers.add_parser(
        "project-wizard",
        help="Interactive wizard to create a new project configuration",
    )

    # project-derive
    p_derive = subparsers.add_parser(
        "project-derive",
        help="Create a new project derived from an existing one "
        "(shared infra, fresh agent config)",
    )
    _a = p_derive.add_argument("source_id", help="Source project ID to derive from")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass
    p_derive.add_argument("new_id", help="New project ID")

    # presets
    p_presets = subparsers.add_parser("presets", help="Manage agent config presets")
    presets_sub = p_presets.add_subparsers(dest="presets_cmd", required=True)
    p_presets_list = presets_sub.add_parser("list", help="List available presets for a project")
    _a = p_presets_list.add_argument("project_id")
    try:
        _a.completer = _complete_project_ids  # type: ignore[attr-defined]
    except AttributeError:
        pass


def dispatch(args) -> bool:
    """Handle project management commands.  Returns True if handled."""
    if args.cmd == "projects":
        projs = list_projects()
        if not projs:
            print("No projects found")
        else:
            print("Known projects:")
            for p in projs:
                upstream = p.upstream_url or "-"
                print(f"- {p.id} [{p.security_class}] upstream={upstream} config_root={p.root}")
        return True
    if args.cmd == "project-derive":
        target = derive_project(args.source_id, args.new_id)
        print(f"Derived project '{args.new_id}' from '{args.source_id}' at {target}")
        print("Next steps:")
        print(f"  1. Edit {target / 'project.yml'} (customize agent: section)")
        print(f"  2. Initialize: luskctl project-init {args.new_id}")
        print("  Tip: global presets are shared across projects (see luskctl config)")
        return True
    if args.cmd == "project-wizard":
        run_wizard(init_fn=cmd_project_init)
        return True
    if args.cmd == "presets":
        if args.presets_cmd == "list":
            presets = list_presets(args.project_id)
            if not presets:
                print(f"No presets found for project '{args.project_id}'")
            else:
                print(f"Presets for '{args.project_id}':")
                for info in presets:
                    print(f"  - {info.name} ({info.source})")
        return True
    return False
