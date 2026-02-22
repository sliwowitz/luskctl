"""Agent config resolution: layered merging across global, project, preset, and CLI scopes.

Builds a :class:`~luskctl.lib._util.config_stack.ConfigStack` from up to four
layers and returns a single merged agent-config dict that can be fed directly
into :func:`~luskctl.lib.containers.agents.prepare_agent_config_dir`.
"""

from __future__ import annotations

from luskctl.lib._util.config_stack import ConfigScope, ConfigStack
from luskctl.lib.core.config import get_global_agent_config
from luskctl.lib.core.projects import load_project


def build_agent_config_stack(
    project_id: str,
    preset: str | None = None,
    cli_overrides: dict | None = None,
) -> ConfigStack:
    """Build config stack: global → project → preset → CLI overrides.

    Returns the :class:`ConfigStack` so callers can either ``.resolve()`` it
    for the merged dict or inspect ``.scopes`` for provenance display.
    """
    stack = ConfigStack()

    # 1. Global agent config
    global_cfg = get_global_agent_config()
    if global_cfg:
        stack.push(ConfigScope("global", None, global_cfg))

    # 2. Project agent config
    project = load_project(project_id)
    if project.agent_config:
        stack.push(ConfigScope("project", project.root / "project.yml", project.agent_config))

    # 3. Preset (if requested)
    if preset:
        from luskctl.lib.core.projects import find_preset_path, load_preset

        preset_data = load_preset(project_id, preset)
        if preset_data:
            stack.push(ConfigScope("preset", find_preset_path(project, preset), preset_data))

    # 4. CLI overrides
    if cli_overrides:
        stack.push(ConfigScope("cli", None, cli_overrides))

    return stack


def resolve_agent_config(
    project_id: str,
    preset: str | None = None,
    cli_overrides: dict | None = None,
) -> dict:
    """Build config stack and return the merged agent config dict.

    Convenience wrapper around :func:`build_agent_config_stack` for callers
    that only need the final resolved dict (e.g. task runners).
    """
    return build_agent_config_stack(
        project_id, preset=preset, cli_overrides=cli_overrides
    ).resolve()
