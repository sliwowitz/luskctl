"""Headless (autopilot) provider registry for multi-agent support.

Defines a frozen dataclass per provider and a registry dict, following the
same pattern as ``AuthProvider`` in ``security/auth.py``.  Dispatch functions
resolve the active provider, build the headless CLI command, and generate the
per-provider shell wrapper.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.project_model import Project


@dataclass(frozen=True)
class HeadlessProvider:
    """Describes how to run one AI agent in headless (autopilot) mode."""

    name: str
    """Short key used in CLI dispatch (e.g. ``"claude"``, ``"codex"``)."""

    label: str
    """Human-readable display name (e.g. ``"Claude"``, ``"Codex"``)."""

    binary: str
    """CLI binary name (e.g. ``"claude"``, ``"codex"``, ``"opencode"``)."""

    git_author_name: str
    """GIT_AUTHOR_NAME set inside the container."""

    git_author_email: str
    """GIT_AUTHOR_EMAIL set inside the container."""

    # -- Headless command construction --

    headless_subcommand: str | None
    """Subcommand for headless mode (e.g. ``"exec"`` for codex, ``"run"`` for opencode).

    ``None`` means the binary uses flags only (e.g. ``claude -p``).
    """

    prompt_flag: str
    """Flag for passing the prompt.

    ``"-p"`` for flag-based, ``""`` for positional (after subcommand).
    """

    auto_approve_flags: tuple[str, ...]
    """Flags to enable fully autonomous execution."""

    output_format_flags: tuple[str, ...]
    """Flags for structured output (e.g. ``("--output-format", "stream-json")``)."""

    model_flag: str | None
    """Flag for model override (``"--model"``, ``"--agent"``, or ``None``)."""

    max_turns_flag: str | None
    """Flag for maximum turns (``"--max-turns"`` or ``None``)."""

    verbose_flag: str | None
    """Flag for verbose output (``"--verbose"`` or ``None``)."""

    # -- Session support --

    supports_session_resume: bool
    """Whether the provider supports resuming a previous session."""

    resume_flag: str | None
    """Flag to resume a session (e.g. ``"--resume"``, ``"--session"``)."""

    continue_flag: str | None
    """Flag to continue a session (e.g. ``"--continue"``)."""

    # -- Claude-specific capabilities --

    supports_agents_json: bool
    """Whether the provider supports ``--agents`` JSON (Claude only)."""

    supports_session_hook: bool
    """Whether the provider supports SessionStart hooks (Claude only)."""

    supports_add_dir: bool
    """Whether the provider supports ``--add-dir "/"`` (Claude only)."""

    # -- Log formatting --

    log_format: str
    """Log format identifier: ``"claude-stream-json"`` or ``"plain"``."""


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

HEADLESS_PROVIDERS: dict[str, HeadlessProvider] = {
    "claude": HeadlessProvider(
        name="claude",
        label="Claude",
        binary="claude",
        git_author_name="Claude",
        git_author_email="noreply@anthropic.com",
        headless_subcommand=None,
        prompt_flag="-p",
        auto_approve_flags=("--dangerously-skip-permissions",),
        output_format_flags=("--output-format", "stream-json"),
        model_flag="--model",
        max_turns_flag="--max-turns",
        verbose_flag="--verbose",
        supports_session_resume=True,
        resume_flag="--resume",
        continue_flag=None,
        supports_agents_json=True,
        supports_session_hook=True,
        supports_add_dir=True,
        log_format="claude-stream-json",
    ),
    "codex": HeadlessProvider(
        name="codex",
        label="Codex",
        binary="codex",
        git_author_name="Codex",
        git_author_email="noreply@openai.com",
        headless_subcommand="exec",
        prompt_flag="",
        auto_approve_flags=("--full-auto",),
        output_format_flags=(),
        model_flag="--model",
        max_turns_flag=None,
        verbose_flag=None,
        supports_session_resume=False,
        resume_flag=None,
        continue_flag=None,
        supports_agents_json=False,
        supports_session_hook=False,
        supports_add_dir=False,
        log_format="plain",
    ),
    "copilot": HeadlessProvider(
        name="copilot",
        label="GitHub Copilot",
        binary="copilot",
        git_author_name="Copilot",
        git_author_email="noreply@github.com",
        headless_subcommand=None,
        prompt_flag="-p",
        auto_approve_flags=("--allow-all-tools",),
        output_format_flags=(),
        model_flag="--model",
        max_turns_flag=None,
        verbose_flag=None,
        supports_session_resume=False,
        resume_flag=None,
        continue_flag=None,
        supports_agents_json=False,
        supports_session_hook=False,
        supports_add_dir=False,
        log_format="plain",
    ),
    "vibe": HeadlessProvider(
        name="vibe",
        label="Mistral Vibe",
        binary="vibe",
        git_author_name="Vibe",
        git_author_email="noreply@mistral.ai",
        headless_subcommand=None,
        prompt_flag="--prompt",
        auto_approve_flags=(),
        output_format_flags=(),
        model_flag="--agent",
        max_turns_flag="--max-turns",
        verbose_flag=None,
        supports_session_resume=True,
        resume_flag="--resume",
        continue_flag="--continue",
        supports_agents_json=False,
        supports_session_hook=False,
        supports_add_dir=False,
        log_format="plain",
    ),
    "blablador": HeadlessProvider(
        name="blablador",
        label="Blablador",
        binary="blablador",
        git_author_name="Blablador",
        git_author_email="noreply@hzdr.de",
        headless_subcommand=None,
        prompt_flag="",
        auto_approve_flags=(),
        output_format_flags=(),
        model_flag=None,
        max_turns_flag=None,
        verbose_flag=None,
        supports_session_resume=True,
        resume_flag=None,
        continue_flag="--continue",
        supports_agents_json=False,
        supports_session_hook=False,
        supports_add_dir=False,
        log_format="plain",
    ),
    "opencode": HeadlessProvider(
        name="opencode",
        label="OpenCode",
        binary="opencode",
        git_author_name="OpenCode",
        git_author_email="noreply@opencode.ai",
        headless_subcommand="run",
        prompt_flag="",
        auto_approve_flags=(),
        output_format_flags=(),
        model_flag="--model",
        max_turns_flag=None,
        verbose_flag=None,
        supports_session_resume=True,
        resume_flag="--session",
        continue_flag="--continue",
        supports_agents_json=False,
        supports_session_hook=False,
        supports_add_dir=False,
        log_format="plain",
    ),
}

#: Valid provider names for CLI argument validation.
PROVIDER_NAMES: tuple[str, ...] = tuple(HEADLESS_PROVIDERS.keys())


def get_provider(name: str | None, project: Project) -> HeadlessProvider:
    """Resolve a provider name to a ``HeadlessProvider``.

    Resolution order:
      1. Explicit *name* if given
      2. ``project.default_agent``
      3. ``"claude"`` (ultimate fallback)

    Raises ``SystemExit`` if the resolved name is not in the registry.
    """
    resolved = name or project.default_agent or "claude"
    provider = HEADLESS_PROVIDERS.get(resolved)
    if provider is None:
        valid = ", ".join(sorted(HEADLESS_PROVIDERS))
        raise SystemExit(f"Unknown headless provider {resolved!r}. Valid providers: {valid}")
    return provider


def build_headless_command(
    provider: HeadlessProvider,
    *,
    timeout: int,
    model: str | None = None,
    max_turns: int | None = None,
) -> str:
    """Assemble the bash command string for a headless agent run.

    The command assumes:
    - ``init-ssh-and-repo.sh`` has already set up the workspace
    - The prompt is in ``/home/dev/.luskctl/prompt.txt``
    - For Claude, the ``claude()`` wrapper function is sourced via bash -l

    Returns a bash command string suitable for ``["bash", "-lc", cmd]``.
    """
    if provider.name == "claude":
        return _build_claude_command(provider, timeout=timeout, model=model, max_turns=max_turns)
    return _build_generic_command(provider, timeout=timeout, model=model, max_turns=max_turns)


def _build_claude_command(
    provider: HeadlessProvider,
    *,
    timeout: int,
    model: str | None,
    max_turns: int | None,
) -> str:
    """Build the headless command for Claude using the wrapper function."""
    # Claude uses the claude() wrapper from luskctl-claude.sh which handles
    # --dangerously-skip-permissions, --add-dir, --agents, git env, and timeout
    flags = ""
    if model:
        flags += f" --model {shlex.quote(model)}"
    if max_turns:
        flags += f" --max-turns {int(max_turns)}"

    return (
        f"init-ssh-and-repo.sh &&"
        f" claude --luskctl-timeout {timeout}"
        f" -p "
        '"$(cat /home/dev/.luskctl/prompt.txt)"'
        f"{flags} --output-format stream-json --verbose"
    )


def _build_generic_command(
    provider: HeadlessProvider,
    *,
    timeout: int,
    model: str | None,
    max_turns: int | None,
) -> str:
    """Build the headless command for non-Claude providers."""
    parts = ["init-ssh-and-repo.sh &&"]

    # Timeout wrapper
    parts.append(f"timeout {timeout}")

    # Binary + subcommand
    parts.append(provider.binary)
    if provider.headless_subcommand:
        parts.append(provider.headless_subcommand)

    # Auto-approve flags
    for flag in provider.auto_approve_flags:
        parts.append(flag)

    # Model
    if model and provider.model_flag:
        parts.append(provider.model_flag)
        parts.append(shlex.quote(model))

    # Max turns
    if max_turns and provider.max_turns_flag:
        parts.append(provider.max_turns_flag)
        parts.append(str(int(max_turns)))

    # Output format
    for flag in provider.output_format_flags:
        parts.append(flag)

    # Verbose
    if provider.verbose_flag:
        parts.append(provider.verbose_flag)

    # Prompt — flag-based or positional
    if provider.prompt_flag:
        parts.append(provider.prompt_flag)
    parts.append('"$(cat /home/dev/.luskctl/prompt.txt)"')

    return " ".join(parts)


def generate_agent_wrapper(
    provider: HeadlessProvider,
    project: Project,
    has_agents: bool,
    *,
    claude_wrapper_fn: object | None = None,
) -> str:
    """Generate the shell wrapper function content for a provider.

    For Claude, uses *claude_wrapper_fn* (which should be
    ``agents._generate_claude_wrapper``) to produce the full wrapper with
    ``--dangerously-skip-permissions``, ``--add-dir /``, ``--agents``, and
    session resume support.  The function is passed in by the caller to
    avoid a circular import between this module and ``agents``.

    For other providers, produces a simpler wrapper that sets git env vars
    and delegates to the binary.

    Args:
        claude_wrapper_fn: Callable ``(has_agents, project, skip_permissions) -> str``.
            Required when ``provider.name == "claude"``.
    """
    if provider.name == "claude":
        if claude_wrapper_fn is None:
            raise ValueError("claude_wrapper_fn is required for Claude provider")
        return claude_wrapper_fn(has_agents, project, True)

    return _generate_generic_wrapper(provider, project)


def _generate_generic_wrapper(provider: HeadlessProvider, project: Project) -> str:
    """Generate a shell wrapper for non-Claude providers.

    Sets git identity env vars and wraps the binary with optional timeout
    support (``--luskctl-timeout``), matching the Claude wrapper's interface.
    """
    human_name = shlex.quote(project.human_name or "Nobody")
    human_email = shlex.quote(project.human_email or "nobody@localhost")
    author_name = shlex.quote(provider.git_author_name)
    author_email = shlex.quote(provider.git_author_email)
    binary = provider.binary

    lines = [
        "# Generated by luskctl",
        f"{binary}() {{",
        '    local _timeout=""',
        "    # Extract luskctl-specific flags (must come before agent flags)",
        "    while [[ $# -gt 0 ]]; do",
        '        case "$1" in',
        '            --luskctl-timeout) _timeout="$2"; shift 2 ;;',
        "            *) break ;;",
        "        esac",
        "    done",
    ]

    # Session resume support for providers that have it
    if provider.continue_flag:
        lines.append("    local _resume_args=()")
        lines.append("    [ -s /home/dev/.luskctl/session-id.txt ] && \\")
        lines.append(
            f"        _resume_args+=({provider.continue_flag}"
            ' "$(cat /home/dev/.luskctl/session-id.txt)")'
        )

    # Git env vars and exec — with optional timeout
    lines.append('    if [ -n "$_timeout" ]; then')
    lines.append(f"        GIT_AUTHOR_NAME={author_name} \\")
    lines.append(f"        GIT_AUTHOR_EMAIL={author_email} \\")
    lines.append(f"        GIT_COMMITTER_NAME=${{HUMAN_GIT_NAME:-{human_name}}} \\")
    lines.append(f"        GIT_COMMITTER_EMAIL=${{HUMAN_GIT_EMAIL:-{human_email}}} \\")

    if provider.continue_flag:
        lines.append(f'        timeout "$_timeout" {binary} "${{_resume_args[@]}}" "$@"')
    else:
        lines.append(f'        timeout "$_timeout" {binary} "$@"')

    lines.append("    else")
    lines.append(f"        GIT_AUTHOR_NAME={author_name} \\")
    lines.append(f"        GIT_AUTHOR_EMAIL={author_email} \\")
    lines.append(f"        GIT_COMMITTER_NAME=${{HUMAN_GIT_NAME:-{human_name}}} \\")
    lines.append(f"        GIT_COMMITTER_EMAIL=${{HUMAN_GIT_EMAIL:-{human_email}}} \\")

    if provider.continue_flag:
        lines.append(f'        command {binary} "${{_resume_args[@]}}" "$@"')
    else:
        lines.append(f'        command {binary} "$@"')

    lines.append("    fi")
    lines.append("}")

    return "\n".join(lines) + "\n"
