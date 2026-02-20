import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml  # pip install pyyaml

from .config import (
    build_root,
    config_root,
    get_global_default_agent,
    get_global_human_email,
    get_global_human_name,
    state_root,
    user_projects_root,
)


def _get_global_git_config(key: str) -> str | None:
    """Get a value from the user's global git config.

    Returns None if git is not available or the key is not set.
    """
    try:
        result = subprocess.run(
            ["git", "config", "--global", "--get", key], capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
        return None
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


# ---------- Project model ----------


@dataclass
class Project:
    id: str
    security_class: str  # "online" | "gatekeeping"
    upstream_url: str | None
    default_branch: str
    root: Path

    tasks_root: Path  # workspace dirs
    gate_path: Path  # git gate (mirror) path
    staging_root: Path | None  # gatekeeping only

    ssh_key_name: str | None
    ssh_host_dir: Path | None
    # Optional path to an SSH config template (user-provided). If set, ssh-init
    # will render this template to the shared .ssh/config. Tokens supported:
    #   {{IDENTITY_FILE}}  -> absolute path of the generated private key
    #   {{KEY_NAME}}       -> filename of the generated key (no .pub)
    #   {{PROJECT_ID}}     -> project id
    ssh_config_template: Path | None = None
    # Whether to mount SSH credentials in online mode. Default: True.
    ssh_mount_in_online: bool = True
    # Whether to mount SSH credentials in gatekeeping mode. Default: False.
    ssh_mount_in_gatekeeping: bool = False
    # Whether to expose the upstream URL as a remote named "external" in gatekeeping mode.
    # This allows the container to also reference the real upstream.
    expose_external_remote: bool = False
    # Optional human credentials for git committer (while AI is the author)
    human_name: str | None = None
    human_email: str | None = None
    # Upstream polling configuration for gatekeeping mode
    upstream_polling_enabled: bool = True
    upstream_polling_interval_minutes: int = 5
    # Auto-sync configuration for gatekeeping mode
    auto_sync_enabled: bool = False
    auto_sync_branches: list[str] = field(default_factory=list)
    # Default agent preference (codex, claude, mistral) - used for Web UI and potentially CLI
    default_agent: str | None = None
    # Agent configuration dict (from project.yml agent: section)
    agent_config: dict = field(default_factory=dict)


def _effective_ssh_key_name(project: Project, key_type: str = "ed25519") -> str:
    """Return the SSH key filename that should be used for this project.

    Precedence:
      1. Explicit `ssh.key_name` from project.yml (project.ssh_key_name)
      2. Derived default: id_<type>_<project_id>, e.g. id_ed25519_myproj

    This helper centralizes the default so ssh-init, container env (SSH_KEY_NAME)
    and host-side git helpers all agree even when project.yml omits ssh.key_name.
    """

    if project.ssh_key_name:
        return project.ssh_key_name
    algo = "ed25519" if key_type == "ed25519" else "rsa"
    return f"id_{algo}_{project.id}"


def _find_project_root(project_id: str) -> Path:
    user_root = user_projects_root() / project_id
    sys_root = config_root() / project_id
    if (user_root / "project.yml").is_file():
        return user_root
    if (sys_root / "project.yml").is_file():
        return sys_root
    raise SystemExit(f"Project '{project_id}' not found in {user_root} or {sys_root}")


# ---------- Project listing ----------


def list_projects() -> list[Project]:
    """
    Discover all projects (user + system) and return them as Project objects.
    User projects override system ones with the same id.
    """
    ids: set[str] = set()

    # Collect IDs from user and system project dirs
    for root in (user_projects_root(), config_root()):
        if not root.is_dir():
            continue
        for d in root.iterdir():
            if not d.is_dir():
                continue
            if (d / "project.yml").is_file():
                ids.add(d.name)

    projects: list[Project] = []
    for pid in sorted(ids):
        # load_project will automatically prefer user over system config
        try:
            projects.append(load_project(pid))
        except SystemExit:
            # if a project is broken, skip it rather than crashing the listing
            continue
    return projects


def load_project(project_id: str) -> Project:
    root = _find_project_root(project_id)
    cfg_path = root / "project.yml"
    if not cfg_path.is_file():
        raise SystemExit(f"Missing project.yml in {root}")
    cfg = yaml.safe_load(cfg_path.read_text()) or {}

    proj_cfg = cfg.get("project", {}) or {}
    git_cfg = cfg.get("git", {}) or {}
    ssh_cfg = cfg.get("ssh", {}) or {}
    tasks_cfg = cfg.get("tasks", {}) or {}
    gate_path_cfg = cfg.get("gate", {}) or {}
    gate_cfg = cfg.get("gatekeeping", {}) or {}

    pid = proj_cfg.get("id", project_id)
    sec = proj_cfg.get("security_class", "online")

    sr = state_root()
    tasks_root = Path(tasks_cfg.get("root", sr / "tasks" / pid)).resolve()
    gate_path = Path(gate_path_cfg.get("path", sr / "gate" / f"{pid}.git")).resolve()

    staging_root: Path | None = None
    if sec == "gatekeeping":
        # Default to build_root unless explicitly configured in project.yml
        staging_root = Path(gate_cfg.get("staging_root", build_root() / pid)).resolve()

    upstream_url = git_cfg.get("upstream_url")
    default_branch = git_cfg.get("default_branch", "main")

    ssh_key_name = ssh_cfg.get("key_name")
    ssh_host_dir = (
        Path(ssh_cfg.get("host_dir")).expanduser().resolve() if ssh_cfg.get("host_dir") else None
    )

    # Optional: ssh.config_template (path to a template file). If relative, it's relative to the project root.
    ssh_cfg_template_path: Path | None = None
    if ssh_cfg.get("config_template"):
        cfg_t = Path(str(ssh_cfg.get("config_template")))
        if not cfg_t.is_absolute():
            cfg_t = root / cfg_t
        ssh_cfg_template_path = cfg_t.expanduser().resolve()

    # Optional flag: ssh.mount_in_online (default true)
    ssh_mount_in_online = bool(ssh_cfg.get("mount_in_online", True))
    # Optional flag: ssh.mount_in_gatekeeping (default false)
    ssh_mount_in_gatekeeping = bool(ssh_cfg.get("mount_in_gatekeeping", False))
    # Optional flag: gatekeeping.expose_external_remote (default false)
    # When true, passes the upstream URL to the container as "external" remote
    expose_external_remote = bool(gate_cfg.get("expose_external_remote", False))

    # Optional human credentials for git committer (while AI is the author)
    # Precedence: 1) project.yml, 2) global luskctl config, 3) global git config, 4) defaults
    human_name = git_cfg.get("human_name")
    if not human_name:
        human_name = get_global_human_name()
    if not human_name:
        human_name = _get_global_git_config("user.name")
    if not human_name:
        human_name = "Nobody"

    human_email = git_cfg.get("human_email")
    if not human_email:
        human_email = get_global_human_email()
    if not human_email:
        human_email = _get_global_git_config("user.email")
    if not human_email:
        human_email = "nobody@localhost"

    # Upstream polling configuration
    polling_cfg = gate_cfg.get("upstream_polling", {}) or {}
    upstream_polling_enabled = bool(polling_cfg.get("enabled", True))
    upstream_polling_interval_minutes = int(polling_cfg.get("interval_minutes", 5))

    # Auto-sync configuration
    sync_cfg = gate_cfg.get("auto_sync", {}) or {}
    auto_sync_enabled = bool(sync_cfg.get("enabled", False))
    auto_sync_branches = list(sync_cfg.get("branches", []))

    # Default agent preference (for Web UI and potentially CLI)
    # Precedence: 1) project.yml default_agent, 2) global luskctl config, 3) None (use default)
    default_agent = cfg.get("default_agent")
    if not default_agent:
        default_agent = get_global_default_agent()

    # Agent config section (model, subagents, mcp_servers, etc.)
    agent_cfg = cfg.get("agent", {}) or {}
    # Resolve subagent file: paths relative to project root
    for sa in agent_cfg.get("subagents", []) or []:
        if isinstance(sa, dict) and "file" in sa:
            file_path = Path(str(sa["file"])).expanduser()
            if not file_path.is_absolute():
                file_path = root / file_path
            sa["file"] = str(file_path.resolve())

    p = Project(
        id=pid,
        security_class=sec,
        upstream_url=upstream_url,
        default_branch=default_branch,
        root=root.resolve(),
        tasks_root=tasks_root,
        gate_path=gate_path,
        staging_root=staging_root,
        ssh_key_name=ssh_key_name,
        ssh_host_dir=ssh_host_dir,
        ssh_config_template=ssh_cfg_template_path,
        ssh_mount_in_online=ssh_mount_in_online,
        ssh_mount_in_gatekeeping=ssh_mount_in_gatekeeping,
        expose_external_remote=expose_external_remote,
        human_name=human_name,
        human_email=human_email,
        upstream_polling_enabled=upstream_polling_enabled,
        upstream_polling_interval_minutes=upstream_polling_interval_minutes,
        auto_sync_enabled=auto_sync_enabled,
        auto_sync_branches=auto_sync_branches,
        default_agent=default_agent,
        agent_config=agent_cfg,
    )
    return p
