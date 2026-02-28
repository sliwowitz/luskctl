"""Agent configuration: parsing, filtering, and wrapper generation.

Handles .md frontmatter parsing, sub-agent JSON conversion for Claude's
``--agents`` flag, and the ``luskctl-claude.sh`` wrapper function that
sets up git identity and CLI flags inside task containers.
"""

import json
import shlex
from pathlib import Path

import yaml

from .._util.fs import ensure_dir
from ..core.projects import Project

# TODO: future — support global agent definitions in luskctl-config.yml (agent.subagents).
# When implemented, global subagents would be merged with per-project subagents before
# filtering by default/selected. Use a generic merge approach that can be reused across
# different agent runtimes (Claude, Codex, OpenCode, etc.).


def parse_md_agent(file_path: str) -> dict:
    """Parse a .md file with YAML frontmatter into an agent dict.

    Expected format:
        ---
        name: agent-name
        description: ...
        tools: [Read, Grep]
        model: sonnet
        ---
        System prompt body...
    """
    path = Path(file_path)
    if not path.is_file():
        return {}
    content = path.read_text(encoding="utf-8")
    # Split YAML frontmatter from body
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1]) or {}
            if not isinstance(frontmatter, dict):
                frontmatter = {}
            body = parts[2].strip()
            frontmatter["prompt"] = body
            return frontmatter
    # No frontmatter: treat entire file as prompt
    return {"prompt": content.strip()}


# All native Claude agent fields to pass through to --agents JSON.
_CLAUDE_AGENT_FIELDS = frozenset(
    {
        "description",
        "tools",
        "disallowedTools",
        "model",
        "permissionMode",
        "mcpServers",
        "hooks",
        "maxTurns",
        "skills",
        "memory",
        "background",
        "isolation",
    }
)


def _subagents_to_json(
    subagents: list[dict],
    selected_agents: list[str] | None = None,
) -> str:
    """Convert sub-agent list to JSON dict string for --agents flag.

    Filters to include agents where default=True plus any agents whose
    name appears in selected_agents. Output is a JSON dict keyed by
    agent name (the format expected by Claude's --agents flag).

    - file: refs are parsed from .md YAML frontmatter + body
    - Inline defs: system_prompt -> prompt, pass through native Claude fields
    - Strips non-Claude fields: default, name (name becomes the dict key)
    """
    result: dict[str, dict] = {}
    selected = set(selected_agents) if selected_agents else set()

    for sa in subagents:
        # Resolve file references first
        if "file" in sa:
            agent = parse_md_agent(sa["file"])
            if not agent:
                continue
            # Merge the default flag from the YAML definition
            if "default" in sa:
                agent["default"] = sa["default"]
        else:
            agent = dict(sa)  # shallow copy

        name = agent.get("name")
        if not name:
            continue  # skip agents without a name

        # Filter: include if default=True OR if name in selected_agents
        is_default = agent.get("default", False)
        if not is_default and name not in selected:
            continue

        # Build the output entry
        entry: dict = {}
        for field in _CLAUDE_AGENT_FIELDS:
            if field in agent:
                entry[field] = agent[field]
        # Map system_prompt -> prompt
        if "system_prompt" in agent:
            entry["prompt"] = agent["system_prompt"]
        elif "prompt" in agent:
            entry["prompt"] = agent["prompt"]

        result[name] = entry

    return json.dumps(result)


def _generate_claude_wrapper(
    has_agents: bool,
    project: Project,
    skip_permissions: bool = True,
) -> str:
    """Generate the luskctl-claude.sh wrapper function content.

    Always includes git env vars. Conditionally includes
    --dangerously-skip-permissions, --add-dir /, and --agents.

    The --add-dir / flag gives Claude full filesystem access inside the
    container. The container itself is the security boundary (Podman
    isolation), so restricting file access within it is unnecessary and
    actively harmful — agents need to read/write ~/.claude, /tmp, etc.

    Supports ``--luskctl-timeout <N>`` as the first argument to wrap the
    claude invocation with ``timeout N``.  This allows headless mode to
    use the same wrapper as interactive sessions (the wrapper is the
    single source of truth for CLI flags and git env vars).

    Model, max_turns, and other per-run flags are NOT included here —
    they are passed directly in the headless command or by the user
    in interactive mode.
    """
    human_name = shlex.quote(project.human_name or "Nobody")
    human_email = shlex.quote(project.human_email or "nobody@localhost")

    lines = [
        "# Generated by luskctl",
        "claude() {",
        '    local _timeout=""',
        "    # Extract luskctl-specific flags (must come before claude flags)",
        "    while [[ $# -gt 0 ]]; do",
        '        case "$1" in',
        '            --luskctl-timeout) _timeout="$2"; shift 2 ;;',
        "            *) break ;;",
        "        esac",
        "    done",
        "    local _args=()",
    ]

    if skip_permissions:
        lines.append("    _args+=(--dangerously-skip-permissions)")

    # Give Claude unrestricted filesystem access inside the container.
    # The Podman container itself provides isolation — no need for an
    # additional sandbox layer within it.
    lines.append('    _args+=(--add-dir "/")')

    if has_agents:
        lines.append("    [ -f /home/dev/.luskctl/agents.json ] && \\")
        lines.append('        _args+=(--agents "$(cat /home/dev/.luskctl/agents.json)")')

    # Resume previous session if session file exists (written by SessionStart hook)
    lines.append("    [ -f /home/dev/.luskctl/claude-session.txt ] && \\")
    lines.append('        _args+=(--resume "$(cat /home/dev/.luskctl/claude-session.txt)")')

    # Git env vars and exec — with optional timeout
    lines.append('    if [ -n "$_timeout" ]; then')
    lines.append("        GIT_AUTHOR_NAME=Claude \\")
    lines.append("        GIT_AUTHOR_EMAIL=noreply@anthropic.com \\")
    lines.append(f"        GIT_COMMITTER_NAME=${{HUMAN_GIT_NAME:-{human_name}}} \\")
    lines.append(f"        GIT_COMMITTER_EMAIL=${{HUMAN_GIT_EMAIL:-{human_email}}} \\")
    lines.append('        timeout "$_timeout" command claude "${_args[@]}" "$@"')
    lines.append("    else")
    lines.append("        GIT_AUTHOR_NAME=Claude \\")
    lines.append("        GIT_AUTHOR_EMAIL=noreply@anthropic.com \\")
    lines.append(f"        GIT_COMMITTER_NAME=${{HUMAN_GIT_NAME:-{human_name}}} \\")
    lines.append(f"        GIT_COMMITTER_EMAIL=${{HUMAN_GIT_EMAIL:-{human_email}}} \\")
    lines.append('        command claude "${_args[@]}" "$@"')
    lines.append("    fi")
    lines.append("}")

    return "\n".join(lines) + "\n"


def _write_session_hook(settings_path: Path) -> None:
    """Write a Claude project settings file with a SessionStart hook.

    The hook captures the session ID to ``/home/dev/.luskctl/claude-session.txt``
    on every session start.  The wrapper reads this file to add ``--resume`` on
    subsequent invocations, enabling session continuity across container restarts.

    If the settings file already exists, the hook config is merged into it
    (preserving any existing settings).
    """
    hook_command = (
        "python3 -c \"import json,sys; print(json.load(sys.stdin)['session_id'])\""
        " > /home/dev/.luskctl/claude-session.txt"
    )
    hook_entry = {"hooks": [{"type": "command", "command": hook_command}]}

    if settings_path.is_file():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    else:
        existing = {}

    hooks = existing.setdefault("hooks", {})
    session_hooks = hooks.setdefault("SessionStart", [])
    session_hooks.append(hook_entry)

    settings_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


def prepare_agent_config_dir(
    project: Project,
    task_id: str,
    subagents: list[dict],
    selected_agents: list[str] | None = None,
    prompt: str | None = None,
    skip_permissions: bool = True,
) -> Path:
    """Create and populate the agent-config directory for a task.

    Writes:
    - luskctl-claude.sh (always) — wrapper function with git env vars
    - agents.json (if sub-agents produce non-empty dict after filtering)
    - prompt.txt (if prompt given, headless only)
    - <workspace>/.claude/settings.json — SessionStart hook to capture session ID

    Returns the agent_config_dir path.
    """
    task_dir = project.tasks_root / str(task_id)
    agent_config_dir = task_dir / "agent-config"
    ensure_dir(agent_config_dir)
    # Build agents JSON (may be empty dict "{}")
    has_agents = False
    if subagents:
        agents_json = _subagents_to_json(subagents, selected_agents)
        agents_dict = json.loads(agents_json)
        if agents_dict:  # non-empty dict
            (agent_config_dir / "agents.json").write_text(agents_json, encoding="utf-8")
            has_agents = True

    # Always write the claude wrapper function
    wrapper = _generate_claude_wrapper(has_agents, project, skip_permissions)
    (agent_config_dir / "luskctl-claude.sh").write_text(wrapper, encoding="utf-8")

    # Write SessionStart hook to capture session ID for resume (#239).
    # The hook writes the session ID to /home/dev/.luskctl/claude-session.txt
    # (the per-task agent-config volume), readable from the host after exit.
    # The wrapper reads this file to add --resume on subsequent invocations.
    workspace_claude_dir = task_dir / "workspace" / ".claude"
    ensure_dir(workspace_claude_dir)
    _write_session_hook(workspace_claude_dir / "settings.json")

    # Prompt (headless only)
    if prompt is not None:
        (agent_config_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    return agent_config_dir
