from __future__ import annotations

from pathlib import Path


def render_template(template_path: Path, variables: dict) -> str:
    content = template_path.read_text()
    # Extremely simple token replacement: {{VAR}} -> variables["VAR"]
    for k, v in variables.items():
        content = content.replace(f"{{{{{k}}}}}", str(v))
    return content
