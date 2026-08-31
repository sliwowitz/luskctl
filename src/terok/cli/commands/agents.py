# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Provide commands for AI coding agents.

The commands list agents. The commands set the default selection. The commands
show agent directories.

The command provides three subcommands:

- ``terok agents list [--all]``: List installable agents. Use ``--all``
  to list tools and LLM endpoint providers.
- ``terok agents set [SELECTION]``: Write the global ``image.agents`` value
  to ``config.yml``. Omit ``SELECTION`` to use the interactive selector.
  The value uses the same grammar as ``terok image build --agents`` and the
  new project wizard.
- ``terok agents dir [AGENT]``: Print the shared agent directory. Specify
  ``AGENT`` to print the directory for one agent.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from terok.lib.api.agents import AgentRoster


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``agents`` command group."""
    p = subparsers.add_parser(
        "agents",
        help="List roster entries. Set the default agent selection.",
        description=("List roster entries. Set the global image.agents selection in config.yml."),
    )
    sub = p.add_subparsers(dest="agents_cmd")

    p_list = sub.add_parser(
        "list",
        help="List agents and other roster entries",
        description=(
            "List installable AI coding agents. Use --all to list tools "
            "and LLM endpoint providers. Do not add an LLM endpoint provider "
            "to image.agents. Select an LLM endpoint provider with --provider."
        ),
    )
    p_list.add_argument(
        "--all",
        action="store_true",
        help="Include tools and LLM endpoint providers",
    )

    p_set = sub.add_parser(
        "set",
        help="Set the global image.agents default (interactive when no arg)",
        description=(
            "Write the agent selection to the global config.yml under "
            "image.agents.  Validated against the installed roster before "
            "the file is touched.  Interactive picker when SELECTION is "
            "omitted."
        ),
    )
    p_set.add_argument(
        "selection",
        nargs="?",
        default=None,
        help=(
            'Agent selection in the executor\'s canonical grammar: "all", '
            'a comma list ("claude,vibe"), or "all,-name" to exclude one '
            '("all,-vibe").  Interactive picker when omitted.'
        ),
    )

    p_dir = sub.add_parser(
        "dir",
        help="Print the shared agent-config mounts directory (or one agent's subdir)",
        description=(
            "Print the host directory that holds the per-agent config mounts "
            "bind-mounted into task containers.  With an AGENT, print that "
            "agent's config subdirectory (e.g. _claude-config) instead."
        ),
    )
    p_dir.add_argument(
        "agent",
        nargs="?",
        default=None,
        help="Optional agent name; print its config-mount subdirectory",
    )


def dispatch(args: argparse.Namespace) -> bool:
    """Handle ``terok agents …``.  Returns True if handled."""
    if args.cmd != "agents":
        return False

    sub = getattr(args, "agents_cmd", None)
    if sub is None:
        # Bare ``terok agents`` — print the group's help so users see the verbs.
        print(
            "usage: terok agents {list,set,dir} ...\n\n"
            "  list  List agents and other roster entries\n"
            "  set   Set the global image.agents default in config.yml\n"
            "  dir   Print the shared agent-config mounts directory\n",
            file=sys.stderr,
        )
        return True

    if sub == "list":
        _print_roster(show_all=getattr(args, "all", False))
        return True
    if sub == "set":
        _set_global_default(selection=getattr(args, "selection", None))
        return True
    if sub == "dir":
        _print_mounts_dir(agent=getattr(args, "agent", None))
        return True
    return False


def _print_roster(*, show_all: bool) -> None:
    """Print installable agents. Print all roster entries when *show_all* is true."""
    from terok.lib.api.agents import AgentRoster

    roster = AgentRoster.shared()
    names = roster.all_names if show_all else roster.agent_names

    if not names:
        print("No agents registered.", file=sys.stderr)
        return

    rows = [_roster_row(name, roster) for name in sorted(names)]

    w_name = max(len("NAME"), max(len(r[0]) for r in rows))
    w_type = max(len("TYPE"), max(len(r[1]) for r in rows))
    print(f"{'NAME':<{w_name}}  {'TYPE':<{w_type}}  LABEL")
    for name, entry_type, label in rows:
        print(f"{name:<{w_name}}  {entry_type:<{w_type}}  {label}")

    if any(entry_type == "endpoint" for _, entry_type, _ in rows):
        print(
            "\nSelect LLM endpoint providers with --provider. "
            "Do not add LLM endpoint providers to image.agents."
        )


def _roster_row(name: str, roster: AgentRoster) -> tuple[str, str, str]:
    """Classify one roster entry as a ``(name, type, label)`` table row.

    The type names what the entry is to the operator: an installable
    ``harness``, a selectable LLM ``endpoint``, a plain ``agent``, or an
    auth-only ``tool``.
    """
    agent = roster.agents.get(name)
    provider = roster.providers.get(name)
    auth = roster.auth_providers.get(name)

    if agent is not None:
        label = agent.label
    elif auth is not None:
        label = auth.label
    else:
        label = name

    if provider is not None and provider.serves:
        entry_type = "harness" if name in roster.installs else "endpoint"
    elif agent is not None and agent.protocol and agent.provider_binding is None:
        entry_type = "harness"
    elif agent is not None:
        entry_type = "agent"
    else:
        entry_type = "tool"
    return name, entry_type, label


def _set_global_default(*, selection: str | None) -> None:
    """Validate *selection* and write it to the global ``image.agents`` field."""
    from terok.lib.api.agents import AgentRoster, ExecutorConfigView

    roster = AgentRoster.shared()
    raw = selection if selection is not None else roster.prompt_selection()
    roster.validate_selection(raw)
    path = ExecutorConfigView.set_image_agents(raw)
    print(f"Wrote image.agents = {raw!r} to {path}")


def _print_mounts_dir(*, agent: str | None) -> None:
    """Print the shared agent-config mounts directory, or one agent's subdir.

    The mounts directory holds the per-agent config trees (``_claude-config/``,
    ``_codex-config/``, …) terok bind-mounts into task containers — the place to
    drop skills or other per-agent settings.  It is
    otherwise undiscoverable; this verb surfaces it.

    With *agent*, the agent's config subdirectory is resolved from the roster;
    an unknown agent exits ``2`` with the list of agents that have a mount.
    """
    from terok.lib.core.config import sandbox_live_mounts_dir

    root = sandbox_live_mounts_dir()
    if agent is None:
        print(root)
        return

    from terok.lib.api.agents import AgentRoster

    roster = AgentRoster.shared()
    auth = roster.auth_providers.get(agent)
    if auth is None:
        available = ", ".join(sorted(roster.auth_providers)) or "(none)"
        print(
            f"Unknown agent {agent!r}.  Agents with a config mount: {available}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    print(root / auth.host_dir_name)
