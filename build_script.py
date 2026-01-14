#!/usr/bin/env python3
"""
Build script to preserve git branch information during installation.
This script is called by Poetry during the build process.
"""

import subprocess
from pathlib import Path


def get_git_branch() -> str | None:
    """Get the current git branch name if we're in a git repository."""
    try:
        # Check if we're in a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if result.returncode == 0 and result.stdout.strip() == "true":
            # Get current branch name
            branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if branch_result.returncode == 0:
                return branch_result.stdout.strip()
    except Exception:
        pass
    return None


def write_branch_info(branch_name: str | None):
    """Write branch information to a file that will be included in the package."""
    if branch_name is None:
        return

    # Create a _branch_info.py file in the package
    branch_info_content = f"""
# This file is generated during build to preserve git branch information
# when installing from a git directory using pip/pipx
BRANCH_NAME = "{branch_name}"
"""

    branch_info_path = Path("src/luskctl/_branch_info.py")
    try:
        branch_info_path.write_text(branch_info_content.strip())
        print(f"Preserved branch information: {branch_name}")
    except Exception as e:
        print(f"Warning: Could not write branch info: {e}")


def main():
    """Main build script entry point."""
    print("Running build script to preserve git branch information...")

    branch_name = get_git_branch()
    if branch_name:
        print(f"Detected git branch: {branch_name}")
        write_branch_info(branch_name)
    else:
        print("Not in a git repository or could not detect branch")


if __name__ == "__main__":
    main()
