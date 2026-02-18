"""Interactive project wizard for creating new project configurations."""

import re
import sys
import tempfile
from pathlib import Path

from .editor import open_in_editor

# Template variants: (label, filename)
TEMPLATES: list[tuple[str, str]] = [
    ("Online – Ubuntu 24.04", "online-ubuntu.yml"),
    ("Online – NVIDIA CUDA (GPU)", "online-nvidia.yml"),
    ("Gatekeeping – Ubuntu 24.04", "gatekeeping-ubuntu.yml"),
    ("Gatekeeping – NVIDIA CUDA (GPU)", "gatekeeping-nvidia.yml"),
]

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _validate_project_id(project_id: str) -> str | None:
    """Return an error message if *project_id* is invalid, else ``None``."""
    if not project_id:
        return "Project ID cannot be empty."
    if not _PROJECT_ID_RE.match(project_id):
        return (
            "Project ID must contain only alphanumeric characters, hyphens, "
            "and underscores, and start with an alphanumeric character."
        )
    return None


def _prompt(message: str, default: str = "") -> str:
    """Prompt the user for input with an optional default value."""
    suffix = f" [{default}]" if default else ""
    value = input(f"{message}{suffix}: ").strip()
    return value or default


def _prompt_template() -> int | None:
    """Show numbered template menu and return the 0-based index, or ``None`` on bad input."""
    print("\nSelect a project template:")
    for i, (label, _filename) in enumerate(TEMPLATES, 1):
        print(f"  {i}) {label}")

    choice = input("\nChoice [1-4]: ").strip()
    if not choice.isdigit():
        return None
    idx = int(choice) - 1
    if 0 <= idx < len(TEMPLATES):
        return idx
    return None


def _prompt_docker_snippet() -> str:
    """Optionally open an editor for a custom Docker snippet.

    Returns the snippet text (may be empty if the user skips or the file is empty).
    """
    answer = input("\nAdd a custom Docker snippet? [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        return ""

    with tempfile.NamedTemporaryFile(
        suffix=".dockerfile", prefix="luskctl-snippet-", mode="w", delete=False
    ) as tmp:
        tmp.write("# Add custom Dockerfile commands below.\n# Empty file = no snippet.\n")
        tmp_path = Path(tmp.name)

    try:
        if not open_in_editor(tmp_path):
            print("Editor could not be opened. Skipping snippet.", file=sys.stderr)
            return ""
        content = tmp_path.read_text(encoding="utf-8")
    finally:
        tmp_path.unlink(missing_ok=True)

    # Strip comment-only preamble that the user didn't edit
    lines = [
        line for line in content.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    return "\n".join(lines)


def collect_wizard_inputs() -> dict | None:
    """Run the interactive prompt flow and return collected values.

    Returns a dict with keys: ``template_index``, ``project_id``,
    ``upstream_url``, ``default_branch``, ``user_snippet``.
    Returns ``None`` if the user cancels (Ctrl+C).
    """
    try:
        # Template selection
        template_idx = _prompt_template()
        if template_idx is None:
            print("Invalid template selection.", file=sys.stderr)
            return None

        # Project ID
        while True:
            project_id = _prompt("\nProject ID")
            error = _validate_project_id(project_id)
            if error is None:
                break
            print(error, file=sys.stderr)

        # Upstream URL
        while True:
            upstream_url = _prompt("Upstream git URL")
            if upstream_url:
                break
            print("Upstream URL is required.", file=sys.stderr)

        # Default branch
        default_branch = _prompt("Default branch", default="main")

        # Docker snippet
        user_snippet = _prompt_docker_snippet()

        return {
            "template_index": template_idx,
            "project_id": project_id,
            "upstream_url": upstream_url,
            "default_branch": default_branch,
            "user_snippet": user_snippet,
        }
    except (KeyboardInterrupt, EOFError):
        print("\nWizard cancelled.")
        return None


def run_wizard() -> None:
    """Top-level wizard entry point called by the CLI."""
    print("=== luskctl project wizard ===")
    values = collect_wizard_inputs()
    if values is None:
        return
    print(f"\nCollected configuration for project '{values['project_id']}'.")
