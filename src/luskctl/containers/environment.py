"""Container environment and volume assembly for task containers.

Translates project configuration and security mode into the environment
variables and volume mounts that ``podman run`` needs when launching a
task container.
"""

import os
from pathlib import Path

from ..core.config import get_envs_base_dir
from .._util.fs import _ensure_dir_writable
from ..core.projects import Project

# ---------- Constants ----------

WEB_BACKENDS = ("codex", "claude", "copilot", "mistral")
# Host-side env prefix for passthrough to container web UI.
WEB_ENV_PASSTHROUGH_PREFIX = "LUSKUI_"
WEB_ENV_PASSTHROUGH_KEYS = (
    "ANTHROPIC_API_KEY",
    "CLAUDE_API_KEY",
    "MISTRAL_API_KEY",
)


# ---------- Helpers ----------


def _ensure_dir(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)


def _normalize_web_backend(backend: str | None) -> str | None:
    if backend is None:
        return None
    backend = backend.strip()
    if not backend:
        return None
    return backend.lower()


def _apply_web_env_overrides(
    env: dict,
    backend: str | None,
    project_default_agent: str | None = None,
) -> dict:
    """Return a copy of env with web-specific overrides applied.

    Backend precedence (highest to lowest):
    1. Explicit backend argument (from CLI --backend flag)
    2. DEFAULT_AGENT environment variable on host
    3. project_default_agent (from project.yml or global config)
    4. Default: "codex"
    """
    merged = dict(env)

    # Determine effective backend with precedence
    effective_backend = _normalize_web_backend(backend)
    if not effective_backend:
        effective_backend = _normalize_web_backend(os.environ.get("DEFAULT_AGENT"))
    if not effective_backend:
        effective_backend = _normalize_web_backend(project_default_agent)
    if not effective_backend:
        effective_backend = "codex"

    # Validate against known backends; fall back to default on typos
    if effective_backend not in WEB_BACKENDS:
        effective_backend = "codex"

    # Export as LUSKUI_BACKEND to the container
    merged["LUSKUI_BACKEND"] = effective_backend

    for key, value in os.environ.items():
        if key.startswith(WEB_ENV_PASSTHROUGH_PREFIX) and key not in merged:
            merged[key] = value

    for key in WEB_ENV_PASSTHROUGH_KEYS:
        if key not in merged:
            val = os.environ.get(key)
            if val:
                merged[key] = val

    return merged


# ---------- Main builder ----------


def _build_task_env_and_volumes(project: Project, task_id: str) -> tuple[dict, list[str]]:
    """Compose environment and volume mounts for a task container.

    - Mount per-task workspace subdir to /workspace (host-explorable).
    - Mount shared codex config dir to /home/dev/.codex (read-write).
    - Mount shared Claude config dir to /home/dev/.claude (read-write).
    - Optionally mount per-project SSH config dir to /home/dev/.ssh (read-write).
    - Provide REPO_ROOT and git info for the init script.
    """
    # Per-task workspace directory as a subdirectory of the task dir
    task_dir = project.tasks_root / str(task_id)
    repo_dir = task_dir / "workspace"
    repo_dir.mkdir(parents=True, exist_ok=True)

    # Shared env mounts
    envs_base = get_envs_base_dir()
    codex_host_dir = envs_base / "_codex-config"
    claude_host_dir = envs_base / "_claude-config"
    vibe_host_dir = envs_base / "_vibe-config"
    blablador_host_dir = envs_base / "_blablador-config"
    opencode_config_host_dir = envs_base / "_opencode-config"
    opencode_data_host_dir = envs_base / "_opencode-data"
    opencode_state_host_dir = envs_base / "_opencode-state"
    # Prefer project-configured SSH host dir if set
    ssh_host_dir = project.ssh_host_dir or (envs_base / f"_ssh-config-{project.id}")
    _ensure_dir_writable(codex_host_dir, "Codex config")
    _ensure_dir_writable(claude_host_dir, "Claude config")
    _ensure_dir_writable(vibe_host_dir, "Vibe config")
    _ensure_dir_writable(blablador_host_dir, "Blablador config")
    _ensure_dir_writable(opencode_config_host_dir, "OpenCode config")
    _ensure_dir_writable(opencode_data_host_dir, "OpenCode data")
    _ensure_dir_writable(opencode_state_host_dir, "OpenCode state")

    env = {
        "PROJECT_ID": project.id,
        "TASK_ID": task_id,
        # Tell init script where to clone/sync the repo
        "REPO_ROOT": "/workspace",
        # Default reset mode is none; allow overriding via container env if needed
        "GIT_RESET_MODE": os.environ.get("LUSKCTL_GIT_RESET_MODE", "none"),
        # Keep Claude Code config under the shared mount regardless of HOME.
        "CLAUDE_CONFIG_DIR": "/home/dev/.claude",
        # Human credentials for git committer (AI agent is the author)
        "HUMAN_GIT_NAME": project.human_name or "Nobody",
        "HUMAN_GIT_EMAIL": project.human_email or "nobody@localhost",
    }

    volumes: list[str] = []

    # Per-task workspace mount (container-specific, not shared)
    volumes.append(f"{repo_dir}:/workspace:Z")

    # Shared codex credentials/config (shared between containers)
    volumes.append(f"{codex_host_dir}:/home/dev/.codex:z")
    # Shared Claude credentials/config (shared between containers)
    volumes.append(f"{claude_host_dir}:/home/dev/.claude:z")
    # Shared Mistral Vibe credentials/config (shared between containers)
    volumes.append(f"{vibe_host_dir}:/home/dev/.vibe:z")
    # Shared Blablador credentials/config (OpenCode wrapper, shared between containers)
    volumes.append(f"{blablador_host_dir}:/home/dev/.blablador:z")
    # Shared OpenCode config directory (shared between containers)
    volumes.append(f"{opencode_config_host_dir}:/home/dev/.config/opencode:z")
    # Shared OpenCode data directory (used by OpenCode/Blablador, shared between containers)
    volumes.append(f"{opencode_data_host_dir}:/home/dev/.local/share/opencode:z")
    # Shared OpenCode state directory (used by Bun runtime, shared between containers)
    volumes.append(f"{opencode_state_host_dir}:/home/dev/.local/state:z")

    # Security mode specific wiring
    gate_repo = project.gate_path
    gate_parent = gate_repo.parent
    # Mount point inside container for the gate
    gate_mount_inside = "/git-gate/gate.git"

    if project.security_class == "gatekeeping":
        # In gatekeeping mode, hide upstream and SSH. Use the host gate as the only remote.
        if not gate_repo.exists():
            raise SystemExit(
                f"Git gate missing for project '{project.id}'.\n"
                f"Expected at: {gate_repo}\n"
                f"Run 'luskctl gate-sync {project.id}' to create/update the local mirror."
            )

        # Ensure parent exists for mount consistency (gate should already exist)
        gate_parent.mkdir(parents=True, exist_ok=True)
        # Mount gate read-write so tasks can push branches for review (shared between project containers)
        volumes.append(f"{gate_repo}:{gate_mount_inside}:z")
        env["CODE_REPO"] = f"file://{gate_mount_inside}"
        env["GIT_BRANCH"] = project.default_branch or "main"
        # Optionally expose the upstream URL as an "external" remote.
        if project.expose_external_remote and project.upstream_url:
            env["EXTERNAL_REMOTE_URL"] = project.upstream_url
        # Optional SSH mount in gatekeeping mode (shared between project containers)
        if project.ssh_mount_in_gatekeeping and ssh_host_dir.is_dir():
            _ensure_dir_writable(ssh_host_dir, "SSH config")
            volumes.append(f"{ssh_host_dir}:/home/dev/.ssh:z")
    else:
        # Online mode: clone from gate if present, then set upstream to real URL
        if gate_repo.exists():
            gate_parent.mkdir(parents=True, exist_ok=True)
            # Mount gate read-only (shared between project containers)
            volumes.append(f"{gate_repo}:{gate_mount_inside}:z,ro")
            env["CLONE_FROM"] = f"file://{gate_mount_inside}"
        if project.upstream_url:
            env["CODE_REPO"] = project.upstream_url
            env["GIT_BRANCH"] = project.default_branch or "main"
        # Optional SSH config mount in online mode (configurable, shared between project containers)
        if project.ssh_mount_in_online and ssh_host_dir.is_dir():
            _ensure_dir_writable(ssh_host_dir, "SSH config")
            volumes.append(f"{ssh_host_dir}:/home/dev/.ssh:z")

    return env, volumes
