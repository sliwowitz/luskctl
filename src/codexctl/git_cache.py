from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .config import get_envs_base_dir
from .projects import _effective_ssh_key_name, load_project


# ---------- Git cache initialization (host-side) ----------

def _git_env_with_ssh(project) -> dict:
    """Return an env that forces git to use the project's SSH config only.

    - Sets GIT_SSH_COMMAND to use the per-project ssh config via `-F <config>`.
    - Adds `-o IdentitiesOnly=yes` to prevent fallback to keys in ~/.ssh or agent.
    - If a specific private key exists in the project ssh dir (derived from
      project.ssh_key_name), also adds `-o IdentityFile=<that key>` explicitly.

    If the ssh host dir or config is missing, we return the current env.
    """
    env = os.environ.copy()
    ssh_dir = project.ssh_host_dir or (get_envs_base_dir() / f"_ssh-config-{project.id}")
    cfg = Path(ssh_dir) / "config"
    if cfg.is_file():
        ssh_cmd = ["ssh", "-F", str(cfg), "-o", "IdentitiesOnly=yes"]
        # Prefer explicit IdentityFile if we can resolve it. Use the same
        # effective key name logic as ssh-init / containers so that even when
        # ssh.key_name is omitted we still look for the derived default
        # (id_<type>_<project_id>), while keeping this best-effort.
        effective_name = _effective_ssh_key_name(project, key_type="ed25519")
        key_path = Path(ssh_dir) / effective_name
        if key_path.is_file():
            ssh_cmd += ["-o", f"IdentityFile={key_path}"]
        env["GIT_SSH_COMMAND"] = " ".join(map(str, ssh_cmd))
        # Also clear SSH_AUTH_SOCK so agent identities are not considered
        env["SSH_AUTH_SOCK"] = ""
    return env


def init_project_cache(project_id: str, force: bool = False) -> dict:
    """Create or update a host-side git mirror cache for a project.

    - Uses the project's SSH configuration (from ssh-init) via GIT_SSH_COMMAND.
    - If cache doesn't exist or --force is given, performs a fresh `git clone --mirror`.
    - Otherwise, runs `git remote update --prune` to sync.

    Returns a dict with keys: path, upstream_url, created (bool).
    """
    project = load_project(project_id)
    if not project.upstream_url:
        raise SystemExit("Project has no git.upstream_url configured")

    cache_dir = project.cache_path
    cache_dir.parent.mkdir(parents=True, exist_ok=True)

    # Determine if upstream requires SSH and ensure we only use the project's SSH dir
    upstream = project.upstream_url
    is_ssh_upstream = False
    try:
        is_ssh_upstream = upstream.startswith("git@") or upstream.startswith("ssh://")
    except Exception:
        is_ssh_upstream = False

    # Resolve the project's ssh dir and config path (created by ssh-init)
    ssh_dir = project.ssh_host_dir or (get_envs_base_dir() / f"_ssh-config-{project.id}")
    ssh_cfg_path = Path(ssh_dir) / "config"

    if is_ssh_upstream:
        # For SSH upstreams, require the project-specific config; do NOT fall back to ~/.ssh
        if not ssh_cfg_path.is_file():
            raise SystemExit(
                "SSH upstream detected but project SSH config is missing.\n"
                f"Expected SSH config at: {ssh_cfg_path}\n"
                f"Run 'codexctl ssh-init {project.id}' first to generate keys and config."
            )

    # Build git environment that forces use of the project's SSH config (if present)
    env = _git_env_with_ssh(project)

    created = False
    if force and cache_dir.exists():
        # Remove to ensure clean mirror
        try:
            if cache_dir.is_dir():
                shutil.rmtree(cache_dir)
        except Exception:
            pass

    if not cache_dir.exists():
        # Create a mirror clone
        cmd = ["git", "clone", "--mirror", project.upstream_url, str(cache_dir)]
        try:
            subprocess.run(cmd, check=True, env=env)
        except FileNotFoundError:
            raise SystemExit("git not found on host; please install git")
        except subprocess.CalledProcessError as e:
            raise SystemExit(f"git clone --mirror failed: {e}")
        created = True
    else:
        # Update existing mirror
        try:
            subprocess.run(["git", "-C", str(cache_dir), "remote", "update", "--prune"], check=True, env=env)
        except subprocess.CalledProcessError as e:
            raise SystemExit(f"git remote update failed: {e}")

    return {"path": str(cache_dir), "upstream_url": project.upstream_url, "created": created}
