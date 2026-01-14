"""Version and branch information for luskctl.

This module provides a single source of truth for version and branch information,
used by both the CLI (--version) and TUI (title bar).
"""

import subprocess
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

      3. INSTALLED FROM GIT DIRECTORY:
         `pip install /path/to/luskctl` or `pipx install /path/to/luskctl`
         where the path is a git repository.
         -> Show branch name (via _branch_info.py generated at build time)
            unless the build was from a tagged release commit.

      4. INSTALLED FROM RELEASE TARBALL:
         `pip install luskctl-X.Y.Z.tar.gz` from a release artifact.
         -> Show version only. The placeholder _branch_info.py has None.

    IMPLEMENTATION:
    ---------------
    The branch detection uses two strategies with a priority order:

    STRATEGY 1 - Preserved branch info (for pip/pipx installs from git):
      A placeholder _branch_info.py (with BRANCH_NAME = None) is checked into the
      repo to ensure it's included in the wheel. The Poetry build script
      (build_script.py, configured via [tool.poetry.build]) runs during
      `pip install <git-dir>` and overwrites the placeholder with the actual branch
      name. For tagged releases (vX.Y.Z), the placeholder is left unchanged.

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
    # Determine the repository root (3 levels up: version.py -> lib -> luskctl -> src -> repo)
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

    # Strategy 1: Check for _branch_info.py (placeholder overwritten by build_script.py)
    # The placeholder has BRANCH_NAME = None; build_script.py overwrites it with the
    # actual branch name during pip/pipx install from a git directory (non-release).
    try:
        from luskctl import _branch_info

        if hasattr(_branch_info, "BRANCH_NAME") and _branch_info.BRANCH_NAME:
            return version, _branch_info.BRANCH_NAME
    except ImportError:
        # _branch_info.py doesn't exist: either PyPI install, dev mode, or release build
        pass

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
