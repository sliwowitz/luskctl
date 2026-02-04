"""Version and branch information for luskctl.

This module provides a single source of truth for version and branch information,
used by both the CLI (--version) and TUI (title bar).
"""

import json
import subprocess
from importlib import metadata
from pathlib import Path


def get_version_info() -> tuple[str, str | None]:
    """Get version and branch information.

    This function implements a multi-layered strategy to determine version and branch
    information across different installation/execution contexts.

    DESIGN RATIONALE:
    -----------------
    luskctl can be run in several ways, and we want to show the branch name only
    when it's meaningful to the user:

      1. DEVELOPMENT MODE (git checkout):
         Run directly via `poetry run luskctl-tui` from a git working directory.
         -> Show branch name (via live git detection) unless on a tagged release.

      2. INSTALLED FROM PyPI (official release):
         Standard `pip install luskctl` from PyPI.
         -> Show version only. No branch info available or meaningful.

      3. INSTALLED FROM VCS URL:
         `pip install git+https://...` or `pipx install git+https://...`.
         -> Show requested revision (branch/tag/commit) from PEP 610 metadata.

      4. INSTALLED FROM LOCAL PATH / RELEASE TARBALL:
         `pip install /path/to/luskctl` or `pip install luskctl-X.Y.Z.tar.gz`.
         -> Show version only. Branch info is not available/meaningful.

    IMPLEMENTATION:
    ---------------
    The branch detection uses three strategies with a priority order:

    STRATEGY 1 - PEP 610 metadata (for VCS installs):
      When installed from a VCS URL, pip records PEP 610 metadata in
      direct_url.json. If present, we use requested_revision (or commit_id)
      for display, without mutating any source files.

    STRATEGY 2 - Live git detection (for development mode):
      When running from source (detected by presence of pyproject.toml), query
      git directly for the current branch. Check for tagged releases and suppress
      the branch name if HEAD is at a vX.Y.Z tag.

    VERSION DETECTION:
      - Primary: Import __version__ from the installed luskctl package
      - Fallback: Read from pyproject.toml (development mode only)

    Returns:
        tuple: (version_string, branch_name) where branch_name is None for releases
               or when branch info is not available/meaningful
    """
    # Determine the repository root (4 levels up: version.py -> lib -> luskctl -> src -> repo)
    # This path is only meaningful in development mode; after pip install it points elsewhere
    repo_root = Path(__file__).parent.parent.parent.parent

    # --- VERSION DETECTION ---
    # Import version from luskctl package (single source of truth)
    try:
        from luskctl import __version__

        version = __version__
    except (ImportError, AttributeError):
        version = "unknown"

    # --- BRANCH DETECTION ---
    branch_name = None

    # Strategy 1: PEP 610 direct_url.json (VCS installs)
    pep610_revision = _get_pep610_revision()
    if pep610_revision:
        return version, pep610_revision

    # Strategy 2: Live git detection (development mode only)
    # Only attempt if pyproject.toml exists, indicating we're in a source checkout
    pyproject_path = repo_root / "pyproject.toml"
    if pyproject_path.exists():
        try:
            # Verify we're inside a git repository
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                text=True,
                timeout=1,
                cwd=str(repo_root),
            )
            if result.returncode == 0 and result.stdout.strip() == "true":
                # Get current branch name
                branch_result = subprocess.run(
                    ["git", "branch", "--show-current"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                    cwd=str(repo_root),
                )
                if branch_result.returncode == 0:
                    detected_branch = branch_result.stdout.strip()
                    if detected_branch:
                        # Check if HEAD is at a tagged release (vX.Y.Z format)
                        # If so, suppress branch name - releases show version only
                        tag_result = subprocess.run(
                            ["git", "describe", "--exact-match", "--tags", "HEAD"],
                            capture_output=True,
                            text=True,
                            timeout=1,
                            cwd=str(repo_root),
                        )
                        is_release = (
                            tag_result.returncode == 0
                            and tag_result.stdout.strip().startswith("v")
                            and len(tag_result.stdout.strip()) > 1
                            and tag_result.stdout.strip()[1].isdigit()
                        )
                        if not is_release:
                            branch_name = detected_branch
        except Exception:
            # Git not available or error - continue without branch info
            pass

    return version, branch_name


def _get_pep610_revision(dist_name: str = "luskctl") -> str | None:
    """Return VCS revision from PEP 610 metadata, if available."""
    try:
        dist = metadata.distribution(dist_name)
        direct_url = dist.read_text("direct_url.json")
    except (metadata.PackageNotFoundError, FileNotFoundError):
        return None

    if not direct_url:
        return None

    try:
        data = json.loads(direct_url)
    except json.JSONDecodeError:
        return None

    vcs_info = data.get("vcs_info")
    if not isinstance(vcs_info, dict):
        return None

    requested_revision = vcs_info.get("requested_revision")
    if requested_revision:
        return requested_revision

    commit_id = vcs_info.get("commit_id")
    if commit_id:
        return commit_id

    return None


def format_version_string(version: str, branch: str | None) -> str:
    """Format version and branch into a display string.

    Args:
        version: The version string (e.g., "0.3.1")
        branch: The branch name or None

    Returns:
        Formatted string like "0.3.1" or "0.3.1 [feature-branch]"
    """
    if branch:
        return f"{version} [{branch}]"
    return version
