#!/usr/bin/env bash
set -euo pipefail

# start-claude.sh -- Unified Claude Code runner for luskctl containers.
#
# Handles two modes:
#   1. Headless (automated): prompt.txt exists → run claude -p with streaming JSON
#   2. Interactive (subagent): no prompt.txt → run claude interactively
#
# Config is read from /home/dev/.luskctl/agent-config.json (mounted by luskctl).
# CLI overrides via LUSKCTL_AGENT_MODEL and LUSKCTL_AGENT_MAX_TURNS env vars.

CONFIG_DIR="/home/dev/.luskctl"
CONFIG_FILE="${CONFIG_DIR}/agent-config.json"
PROMPT_FILE="${CONFIG_DIR}/prompt.txt"

# Set git author for Claude's commits
export GIT_AUTHOR_NAME="Claude"
export GIT_AUTHOR_EMAIL="noreply@anthropic.com"
export GIT_COMMITTER_NAME="${HUMAN_GIT_NAME:-Nobody}"
export GIT_COMMITTER_EMAIL="${HUMAN_GIT_EMAIL:-nobody@localhost}"

cd /workspace

# Build claude command arguments
CLAUDE_ARGS=()

# Read config file if present
if [[ -f "$CONFIG_FILE" ]]; then
    # Extract model
    model=$(jq -r '.model // empty' "$CONFIG_FILE" 2>/dev/null || true)
    [[ -n "$model" ]] && CLAUDE_ARGS+=(--model "$model")

    # Extract max_turns
    max_turns=$(jq -r '.max_turns // empty' "$CONFIG_FILE" 2>/dev/null || true)
    [[ -n "$max_turns" ]] && CLAUDE_ARGS+=(--max-turns "$max_turns")

    # Extract system_prompt
    sys_prompt=$(jq -r '.system_prompt // empty' "$CONFIG_FILE" 2>/dev/null || true)
    [[ -n "$sys_prompt" ]] && CLAUDE_ARGS+=(--append-system-prompt "$sys_prompt")

    # Extract agents (subagents)
    agents=$(jq -c '.agents // empty' "$CONFIG_FILE" 2>/dev/null || true)
    [[ -n "$agents" && "$agents" != "null" ]] && CLAUDE_ARGS+=(--agents "$agents")

    # Extract MCP servers -> write to .mcp.json for --mcp-config
    mcp=$(jq -c '.mcpServers // empty' "$CONFIG_FILE" 2>/dev/null || true)
    if [[ -n "$mcp" && "$mcp" != "null" ]]; then
        echo "{\"mcpServers\": $mcp}" > "${CONFIG_DIR}/mcp.json"
        CLAUDE_ARGS+=(--mcp-config "${CONFIG_DIR}/mcp.json")
    fi
fi

# CLI overrides via env vars (set by luskctl)
[[ -n "${LUSKCTL_AGENT_MODEL:-}" ]] && CLAUDE_ARGS+=(--model "$LUSKCTL_AGENT_MODEL")
[[ -n "${LUSKCTL_AGENT_MAX_TURNS:-}" ]] && CLAUDE_ARGS+=(--max-turns "$LUSKCTL_AGENT_MAX_TURNS")

# Optional: opt-in to skipping permission checks via config
skip_perms=$(jq -r '.dangerously_skip_permissions // empty' "$CONFIG_FILE" 2>/dev/null || true)
if [[ "$skip_perms" == "true" ]]; then
    CLAUDE_ARGS+=(--dangerously-skip-permissions)
fi

# Optional: opt-in to skipping permission checks via env var
case "${LUSKCTL_AGENT_DANGEROUSLY_SKIP_PERMISSIONS:-}" in
    1|true|TRUE|yes|YES)
        CLAUDE_ARGS+=(--dangerously-skip-permissions)
        ;;
esac

# Determine mode: headless (automated) vs interactive (subagent)
if [[ -f "$PROMPT_FILE" ]]; then
    # Automated mode: run with prompt, non-interactive
    CLAUDE_ARGS+=(--output-format stream-json)
    exec claude -p "$(cat "$PROMPT_FILE")" "${CLAUDE_ARGS[@]}"
else
    # Interactive subagent mode: start claude interactively
    exec claude "${CLAUDE_ARGS[@]}"
fi
