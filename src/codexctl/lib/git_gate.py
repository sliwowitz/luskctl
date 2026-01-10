import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import get_envs_base_dir
from .projects import _effective_ssh_key_name, list_projects, load_project

# ---------- Staleness dataclass ----------


@dataclass
class GateStalenessInfo:
    """Result of comparing gate vs upstream."""

    branch: str
    gate_head: str | None
    upstream_head: str | None
    is_stale: bool
    commits_behind: int | None  # None if couldn't determine
    last_checked: str  # ISO timestamp
    error: str | None


# ---------- Gate sharing validation ----------


def find_projects_sharing_gate(
    gate_path: Path, exclude_project: str = None
) -> list[tuple[str, str | None]]:
    """Find all projects configured to use the same gate path.

    Args:
        gate_path: The gate path to check for
        exclude_project: Project ID to exclude from results (usually the current project)

    Returns:
        List of (project_id, upstream_url) tuples for projects sharing this gate
    """
    gate_path = gate_path.resolve()
    sharing = []

    for project in list_projects():
        if exclude_project and project.id == exclude_project:
            continue
        if project.gate_path.resolve() == gate_path:
            sharing.append((project.id, project.upstream_url))

    return sharing


def validate_gate_upstream_match(project_id: str) -> None:
    """Validate that no other project uses the same gate with a different upstream.

    Raises SystemExit if another project uses the same gate path but has a
    different upstream_url configured.

    Args:
        project_id: The project to validate
    """
    project = load_project(project_id)
    sharing = find_projects_sharing_gate(project.gate_path, exclude_project=project_id)

    for other_id, other_url in sharing:
        if other_url != project.upstream_url:
            raise SystemExit(
                f"Gate path conflict detected!\n"
                f"\n"
                f"  Gate path: {project.gate_path}\n"
                f"\n"
                f"  This project ({project_id}):\n"
                f"    upstream_url: {project.upstream_url}\n"
                f"\n"
                f"  Conflicting project ({other_id}):\n"
                f"    upstream_url: {other_url}\n"
                f"\n"
                f"Projects sharing a gate must have the same upstream_url.\n"
                f"Either change the gate.path in one project's project.yml,\n"
                f"or ensure both projects point to the same upstream repository."
            )


# ---------- Git gate initialization (host-side) ----------


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


def get_gate_last_commit(project_id: str) -> dict | None:
    """Get information about the last commit in the gate repository.

    Returns a dict with keys: commit_hash, commit_date, commit_message, commit_author,
    or None if the gate doesn't exist or is not accessible.

    This is a cheap operation that doesn't update the gate.
    """
    try:
        project = load_project(project_id)
        gate_dir = project.gate_path

        if not gate_dir.exists() or not gate_dir.is_dir():
            return None

        # Build git environment that forces use of the project's SSH config (if present)
        env = _git_env_with_ssh(project)

        # Get the last commit info from the default branch
        # We use git log with specific format to get structured data
        cmd = [
            "git",
            "-C",
            str(gate_dir),
            "log",
            "-1",
            "--pretty=format:%H|%ad|%s|%an",
            "--date=iso",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            return None

        # Parse the output: hash|date|subject|author
        parts = result.stdout.strip().split("|", 3)
        if len(parts) == 4:
            return {
                "commit_hash": parts[0],
                "commit_date": parts[1],
                "commit_message": parts[2],
                "commit_author": parts[3],
            }
        return None

    except Exception:
        # If anything goes wrong, return None - this is a best-effort operation
        return None


def init_project_gate(project_id: str, force: bool = False) -> dict:
    """Create or update a host-side git mirror gate for a project.

    - Uses the project's SSH configuration (from ssh-init) via GIT_SSH_COMMAND.
    - If gate doesn't exist or --force is given, performs a fresh `git clone --mirror`.
    - Otherwise, runs `git remote update --prune` to sync.

    Returns a dict with keys: path, upstream_url, created (bool).
    """
    project = load_project(project_id)
    if not project.upstream_url:
        raise SystemExit("Project has no git.upstream_url configured")

    # Validate no other project uses this gate with a different upstream
    validate_gate_upstream_match(project_id)

    gate_dir = project.gate_path
    gate_dir.parent.mkdir(parents=True, exist_ok=True)

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
    if force and gate_dir.exists():
        # Remove to ensure clean mirror
        try:
            if gate_dir.is_dir():
                shutil.rmtree(gate_dir)
        except Exception:
            # Best-effort cleanup; ignore delete failures.
            pass

    if not gate_dir.exists():
        # Create a mirror clone
        cmd = ["git", "clone", "--mirror", project.upstream_url, str(gate_dir)]
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
            subprocess.run(
                ["git", "-C", str(gate_dir), "remote", "update", "--prune"], check=True, env=env
            )
        except subprocess.CalledProcessError as e:
            raise SystemExit(f"git remote update failed: {e}")

    return {"path": str(gate_dir), "upstream_url": project.upstream_url, "created": created}


# ---------- Upstream comparison functions ----------


def get_upstream_head(project_id: str, branch: str = None) -> dict | None:
    """Query upstream HEAD ref using git ls-remote (cheap, no object download).

    Args:
        project_id: Project identifier
        branch: Specific branch to check (default: project's default_branch)

    Returns:
        Dict with keys: commit_hash, ref_name, upstream_url
        or None if query fails
    """
    try:
        project = load_project(project_id)
        if not project.upstream_url:
            return None

        branch = branch or project.default_branch
        env = _git_env_with_ssh(project)

        # git ls-remote only queries refs, doesn't download objects
        cmd = ["git", "ls-remote", project.upstream_url, f"refs/heads/{branch}"]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)

        if result.returncode != 0:
            return None

        # Parse output: "<commit_hash>\t<ref_name>"
        line = result.stdout.strip()
        if not line:
            return None

        parts = line.split("\t")
        if len(parts) >= 2:
            return {
                "commit_hash": parts[0],
                "ref_name": parts[1],
                "upstream_url": project.upstream_url,
            }
        return None

    except (subprocess.TimeoutExpired, Exception):
        return None


def get_gate_branch_head(project_id: str, branch: str = None) -> str | None:
    """Get the commit hash for a specific branch in the gate.

    Args:
        project_id: Project identifier
        branch: Branch name (default: project's default_branch)

    Returns:
        Commit hash string or None if not found
    """
    try:
        project = load_project(project_id)
        gate_dir = project.gate_path

        if not gate_dir.exists():
            return None

        branch = branch or project.default_branch
        env = _git_env_with_ssh(project)

        # Query the ref in the bare mirror
        cmd = ["git", "-C", str(gate_dir), "rev-parse", f"refs/heads/{branch}"]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)

        if result.returncode == 0:
            return result.stdout.strip()
        return None

    except Exception:
        return None


def compare_gate_vs_upstream(project_id: str, branch: str = None) -> GateStalenessInfo:
    """Compare gate HEAD vs upstream HEAD for a branch.

    Args:
        project_id: Project identifier
        branch: Branch to compare (default: project's default_branch)

    Returns:
        GateStalenessInfo with comparison results
    """
    project = load_project(project_id)
    branch = branch or project.default_branch
    now = datetime.now().isoformat()

    # Get gate HEAD
    gate_head = get_gate_branch_head(project_id, branch)
    if gate_head is None:
        return GateStalenessInfo(
            branch=branch,
            gate_head=None,
            upstream_head=None,
            is_stale=False,
            commits_behind=None,
            last_checked=now,
            error="Gate not initialized",
        )

    # Get upstream HEAD
    upstream_info = get_upstream_head(project_id, branch)
    if upstream_info is None:
        return GateStalenessInfo(
            branch=branch,
            gate_head=gate_head,
            upstream_head=None,
            is_stale=False,
            commits_behind=None,
            last_checked=now,
            error="Could not reach upstream",
        )

    upstream_head = upstream_info["commit_hash"]
    is_stale = gate_head != upstream_head

    # Try to count commits behind using git rev-list
    commits_behind = None
    if is_stale:
        commits_behind = _count_commits_behind(project_id, gate_head, upstream_head)

    return GateStalenessInfo(
        branch=branch,
        gate_head=gate_head,
        upstream_head=upstream_head,
        is_stale=is_stale,
        commits_behind=commits_behind if is_stale else 0,
        last_checked=now,
        error=None,
    )


def _count_commits_behind(project_id: str, local_head: str, remote_head: str) -> int | None:
    """Count commits between local and remote HEAD.

    This requires the remote commits to exist in the gate (they won't if gate
    is stale). Returns None if we can't determine the count.
    """
    try:
        project = load_project(project_id)
        gate_dir = project.gate_path
        env = _git_env_with_ssh(project)

        # This will only work if we've fetched the commits
        # For a stale gate, we may not have remote_head locally
        cmd = ["git", "-C", str(gate_dir), "rev-list", "--count", f"{local_head}..{remote_head}"]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)

        if result.returncode == 0:
            return int(result.stdout.strip())
        return None
    except Exception:
        return None


def sync_gate_branches(project_id: str, branches: list[str] = None) -> dict:
    """Sync specific branches in the gate from upstream.

    Args:
        project_id: Project identifier
        branches: List of branches to sync (default: all via remote update)

    Returns:
        Dict with keys: success, updated_branches, errors
    """
    project = load_project(project_id)
    gate_dir = project.gate_path

    if not gate_dir.exists():
        return {"success": False, "updated_branches": [], "errors": ["Gate not initialized"]}

    # Validate no other project uses this gate with a different upstream
    validate_gate_upstream_match(project_id)

    env = _git_env_with_ssh(project)
    errors = []
    updated = []

    try:
        # Use git remote update for efficiency
        cmd = ["git", "-C", str(gate_dir), "remote", "update", "--prune"]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)

        if result.returncode != 0:
            errors.append(f"remote update failed: {result.stderr}")
        else:
            # If specific branches requested, verify they were updated
            updated = branches if branches else ["all"]

    except subprocess.TimeoutExpired:
        errors.append("Sync timed out")
    except Exception as e:
        errors.append(str(e))

    return {"success": len(errors) == 0, "updated_branches": updated, "errors": errors}
