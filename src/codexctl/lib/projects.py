from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

import yaml  # pip install pyyaml

from .config import build_root, config_root, get_envs_base_dir, state_root, user_projects_root


# ---------- Project model ----------

@dataclass
class Project:
    id: str
    security_class: str          # "online" | "gatekept"
    upstream_url: Optional[str]
    default_branch: str
    root: Path

    tasks_root: Path             # workspace dirs
    cache_path: Path             # future cache
    staging_root: Optional[Path] # gatekept only

    ssh_key_name: Optional[str]
    ssh_host_dir: Optional[Path]
    codex_config_dir: Optional[Path]
    # Optional path to an SSH config template (user-provided). If set, ssh-init
    # will render this template to the shared .ssh/config. Tokens supported:
    #   {{IDENTITY_FILE}}  -> absolute path of the generated private key
    #   {{KEY_NAME}}       -> filename of the generated key (no .pub)
    #   {{PROJECT_ID}}     -> project id
    ssh_config_template: Optional[Path] = None
    # Whether to mount SSH credentials in online mode. Default: True.
    ssh_mount_in_online: bool = True
    # Whether to mount SSH credentials in gatekeeping mode. Default: False.
    ssh_mount_in_gatekeeping: bool = False


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
    codex_cfg = cfg.get("codex", {}) or {}
    tasks_cfg = cfg.get("tasks", {}) or {}
    cache_cfg = cfg.get("cache", {}) or {}
    gate_cfg = cfg.get("gatekeeping", {}) or {}

    pid = proj_cfg.get("id", project_id)
    sec = proj_cfg.get("security_class", "online")

    sr = state_root()
    tasks_root = Path(tasks_cfg.get("root", sr / "tasks" / pid)).resolve()
    cache_path = Path(cache_cfg.get("path", sr / "cache" / f"{pid}.git")).resolve()

    staging_root: Optional[Path] = None
    if sec == "gatekept":
        # Default to build_root unless explicitly configured in project.yml
        staging_root = Path(gate_cfg.get("staging_root", build_root() / pid)).resolve()

    upstream_url = git_cfg.get("upstream_url")
    default_branch = git_cfg.get("default_branch", "main")

    ssh_key_name = ssh_cfg.get("key_name")
    ssh_host_dir = Path(ssh_cfg.get("host_dir")).expanduser().resolve() if ssh_cfg.get("host_dir") else None

    codex_config_dir = Path(codex_cfg.get("config_dir")).expanduser().resolve() if codex_cfg.get("config_dir") else None

    # Optional: ssh.config_template (path to a template file). If relative, it's relative to the project root.
    ssh_cfg_template_path: Optional[Path] = None
    if ssh_cfg.get("config_template"):
        cfg_t = Path(str(ssh_cfg.get("config_template")))
        if not cfg_t.is_absolute():
            cfg_t = (root / cfg_t)
        ssh_cfg_template_path = cfg_t.expanduser().resolve()

    # Optional flag: ssh.mount_in_online (default true)
    ssh_mount_in_online = bool(ssh_cfg.get("mount_in_online", True))
    # Optional flag: ssh.mount_in_gatekeeping (default false)
    ssh_mount_in_gatekeeping = bool(ssh_cfg.get("mount_in_gatekeeping", False))

    p = Project(
        id=pid,
        security_class=sec,
        upstream_url=upstream_url,
        default_branch=default_branch,
        root=root.resolve(),
        tasks_root=tasks_root,
        cache_path=cache_path,
        staging_root=staging_root,
        ssh_key_name=ssh_key_name,
        ssh_host_dir=ssh_host_dir,
        codex_config_dir=codex_config_dir,
        ssh_config_template=ssh_cfg_template_path,
        ssh_mount_in_online=ssh_mount_in_online,
        ssh_mount_in_gatekeeping=ssh_mount_in_gatekeeping,
    )
    return p


# ---------- Project state helpers ----------

def get_project_state(project_id: str) -> dict:
    """Return a summary of per-project infrastructure state.

    The resulting dict contains boolean flags that can be used by UIs
    (including the TUI) to give a quick overview of the project:

    - ``dockerfiles`` - True if all three Dockerfiles (L1/L2/L3) exist
      under the build root for this project.
    - ``images`` - True if podman reports that images ``<id>:l1``,
      ``<id>:l2`` and ``<id>:l3`` exist.
    - ``ssh`` - True if the project SSH directory exists and contains
      a ``config`` file.
    - ``cache`` - True if the project's cache directory exists.
    - ``cache_last_commit`` - Dict with commit info if cache exists, None otherwise.
    """

    project = load_project(project_id)

    # Dockerfiles: look in the same location generate_dockerfiles writes to.
    stage_dir = build_root() / project.id
    dockerfiles = [
        stage_dir / "L1.Dockerfile",
        stage_dir / "L2.Dockerfile",
        stage_dir / "L3.Dockerfile",
    ]
    has_dockerfiles = all(p.is_file() for p in dockerfiles)

    # Images: rely on podman image tags created by build_images().
    has_images = False
    try:
        required_tags = [f"{project.id}:l1", f"{project.id}:l2", f"{project.id}:l3"]
        ok = True
        for tag in required_tags:
            # ``podman image exists`` exits with 0 when the image is present.
            result = subprocess.run(
                ["podman", "image", "exists", tag],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                ok = False
                break
        has_images = ok
    except (FileNotFoundError, OSError):  # podman missing or not usable
        has_images = False

    # SSH: same resolution logic as init_project_ssh(). Consider SSH
    # "ready" when the directory and its config file exist.
    ssh_dir = project.ssh_host_dir or (get_envs_base_dir() / f"_ssh-config-{project.id}")
    ssh_dir = Path(ssh_dir).expanduser().resolve()
    has_ssh = ssh_dir.is_dir() and (ssh_dir / "config").is_file()

    # Cache: a mirror bare repo initialized by init_project_cache(). We
    # treat existence of the directory as "cache present".
    cache_dir = project.cache_path
    has_cache = cache_dir.is_dir()
    
    # Get cache commit info if cache exists
    cache_last_commit = None
    if has_cache:
        # Import here to avoid circular import
        from .git_cache import get_cache_last_commit
        cache_last_commit = get_cache_last_commit(project_id)

    return {
        "dockerfiles": has_dockerfiles,
        "images": has_images,
        "ssh": has_ssh,
        "cache": has_cache,
        "cache_last_commit": cache_last_commit,
    }
