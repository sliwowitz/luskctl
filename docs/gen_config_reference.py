# SPDX-FileCopyrightText: 2025 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Generate a config reference page from the Pydantic YAML schema models.

Runs during ``mkdocs build`` via the mkdocs-gen-files plugin.  Introspects
:class:`~terok.lib.core.yaml_schema.RawProjectYaml` and
:class:`~terok.lib.core.yaml_schema.RawGlobalConfig` to produce:

- Per-section Markdown tables with field name, type, default, and description
- A full annotated YAML example for each config file

The Pydantic models are the **single source of truth** — if a field exists in
the schema, it appears in the docs automatically.
"""

from __future__ import annotations

import io
import json
from typing import get_args, get_origin

import mkdocs_gen_files
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from terok.lib.core.yaml_schema import RawGlobalConfig, RawProjectYaml

_MD_RULE = "---\n\n"
"""Markdown horizontal rule with trailing blank line."""

# ---------------------------------------------------------------------------
# Human-friendly descriptions for fields that lack Field(description=...).
# Key format: "section.field" (dot-separated YAML path).
# ---------------------------------------------------------------------------

_FIELD_DOCS: dict[str, str] = {
    # project.yml — project section
    "project.id": "Unique project identifier (lowercase, ``[a-z0-9_-]``)",
    "project.name": "Human-readable project name (display only)",
    "project.security_class": "Security mode: ``online`` (direct push) or ``gatekeeping`` (gated mirror)",
    # git
    "git.upstream_url": "Repository URL to clone into task containers",
    "git.default_branch": "Default branch name (e.g. ``main``)",
    "git.human_name": "Human name for git committer identity",
    "git.human_email": "Human email for git committer identity",
    "git.authorship": "How agent/human map to git author/committer. Values: ``agent-human``, ``human-agent``, ``agent``, ``human``",
    # ssh
    "ssh.key_name": "SSH key filename (default: ``id_ed25519_<project_id>``)",
    "ssh.host_dir": "Host directory containing SSH keys to mount",
    "ssh.config_template": "Path to an SSH config template file (supports ``{{IDENTITY_FILE}}``, ``{{KEY_NAME}}``, ``{{PROJECT_ID}}``)",
    "ssh.mount_in_online": "Mount SSH credentials in online mode containers",
    "ssh.mount_in_gatekeeping": "Mount SSH credentials in gatekeeping mode containers",
    # tasks
    "tasks.root": "Override task workspace root directory",
    "tasks.name_categories": "Word categories for auto-generated task names (string or list of strings)",
    # gate
    "gate.path": "Override git gate (mirror) path",
    # gatekeeping
    "gatekeeping.staging_root": "Staging directory for gatekeeping builds",
    "gatekeeping.expose_external_remote": "Add upstream URL as ``external`` remote in gatekeeping containers",
    "gatekeeping.upstream_polling.enabled": "Poll upstream for new commits",
    "gatekeeping.upstream_polling.interval_minutes": "Polling interval in minutes",
    "gatekeeping.auto_sync.enabled": "Auto-sync branches from upstream to gate",
    "gatekeeping.auto_sync.branches": "Branch names to auto-sync",
    # run
    "run.shutdown_timeout": "Seconds to wait before SIGKILL on container stop",
    "run.gpus": 'GPU passthrough: ``true``, ``"all"``, or omit to disable',
    # shield
    "shield.drop_on_task_start": "Drop shield (bypass firewall) when task container starts",
    # docker
    "docker.base_image": "Base Docker image for container builds",
    "docker.user_snippet_inline": "Inline Dockerfile snippet injected into the project image",
    "docker.user_snippet_file": "Path to a file containing a Dockerfile snippet",
    # top-level
    "default_agent": "Default agent provider (e.g. ``claude``, ``codex``)",
    "agent": "Agent configuration dict (model, subagents, MCP servers, etc.)",
    # global config — ui
    "ui.base_port": "Base port for web UI task containers",
    # envs
    "envs.base_dir": "Host directory for shared credential mounts (SSH, agent configs)",
    # paths
    "paths.state_root": "Writable state directory (tasks, caches, builds)",
    "paths.build_root": "Build artifacts directory (generated Dockerfiles)",
    "paths.user_projects_root": "User projects directory (per-user project configs)",
    "paths.global_presets_dir": "Global presets directory (shared across all projects)",
    # tui
    "tui.default_tmux": "Default to tmux mode when launching the TUI",
    # logs
    "logs.partial_streaming": "Enable typewriter-effect streaming for log viewing",
    # shield (global)
    "shield.bypass_firewall_no_protection": "**Dangerous**: disable egress firewall entirely",
    "shield.profiles": "Named shield profiles for per-project firewall rules",
    "shield.audit": "Enable shield audit logging",
    # gate_server
    "gate_server.port": "Gate server listen port",
    "gate_server.suppress_systemd_warning": "Suppress the systemd unit installation suggestion",
}


def _type_str(field_info: FieldInfo) -> str:
    """Produce a human-readable type string from a Pydantic FieldInfo."""
    annotation = field_info.annotation
    if annotation is None:
        return "any"

    origin = get_origin(annotation)
    args = get_args(annotation)

    # Handle Union types (e.g. str | None from Optional)
    if origin is type(str | None):  # types.UnionType
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            inner = _simple_type_name(non_none[0])
            return f"{inner} or null"
        return " or ".join(_simple_type_name(a) for a in non_none) + " or null"

    # Handle list[str] etc.
    if origin is list:
        inner = _simple_type_name(args[0]) if args else "any"
        return f"list of {inner}"

    if origin is dict:
        return "mapping"

    return _simple_type_name(annotation)


def _simple_type_name(t: type) -> str:
    """Return a short name for a type."""
    names = {str: "string", int: "integer", bool: "boolean", float: "number"}
    return names.get(t, getattr(t, "__name__", str(t)))


def _factory_default_repr(field_info: FieldInfo) -> str:
    """Produce a default-value string for fields with ``default_factory``."""
    try:
        val = field_info.default_factory()  # type: ignore[misc]
        if isinstance(val, BaseModel):
            return "*section defaults*"
        if isinstance(val, list):
            return "``[]``"
        if isinstance(val, dict):
            return "``{}``"
    except Exception:
        pass
    return "*computed*"


def _scalar_default_repr(d: object) -> str:
    """Produce a default-value string for a scalar default."""
    if d is None:
        return "—"
    if isinstance(d, bool):
        return f"``{str(d).lower()}``"
    if isinstance(d, (int, float)):
        return f"``{d}``"
    if isinstance(d, str):
        return f'``"{d}"``' if d else "*empty*"
    return f"``{d}``"


def _default_repr(field_info: FieldInfo) -> str:
    """Produce a human-readable default value string."""
    if field_info.is_required():
        return "*required*"
    if field_info.default_factory is not None:
        return _factory_default_repr(field_info)
    return _scalar_default_repr(field_info.default)


def _is_section_field(field_info: FieldInfo) -> bool:
    """Check if a field is a nested Pydantic section model."""
    ann = field_info.annotation
    if ann is None:
        return False
    return isinstance(ann, type) and issubclass(ann, BaseModel)


def _yaml_default(field_info: FieldInfo) -> str:
    """Return the YAML-formatted default value for a field."""
    if field_info.default_factory is not None:
        try:
            val = field_info.default_factory()
            if isinstance(val, list):
                return "[]"
            if isinstance(val, dict):
                return "{}"
        except Exception:
            pass
        return ""
    d = field_info.default
    if d is None:
        return ""
    if isinstance(d, bool):
        return str(d).lower()
    if isinstance(d, str):
        return f'"{d}"' if " " in d or not d else d
    return str(d)


def _render_section_table(
    buf: io.StringIO,
    model_class: type[BaseModel],
    prefix: str,
    *,
    heading_level: int = 3,
) -> None:
    """Render a Markdown table for one section model, recursing into sub-sections."""
    hashes = "#" * heading_level
    section_name = prefix.rstrip(".")
    buf.write(f"{hashes} `{section_name}:`\n\n")

    # Collect leaf fields and sub-section fields separately
    leaf_fields: list[tuple[str, str, FieldInfo]] = []
    sub_sections: list[tuple[str, type[BaseModel], FieldInfo]] = []

    for name, field_info in model_class.model_fields.items():
        if _is_section_field(field_info):
            sub_sections.append((name, field_info.annotation, field_info))
        else:
            leaf_fields.append((name, prefix + name, field_info))

    if leaf_fields:
        buf.write("| Key | Type | Default | Description |\n")
        buf.write("|-----|------|---------|-------------|\n")
        for name, dotpath, fi in leaf_fields:
            type_s = _type_str(fi)
            default_s = _default_repr(fi)
            desc = _FIELD_DOCS.get(dotpath, fi.description or "")
            buf.write(f"| `{name}` | {type_s} | {default_s} | {desc} |\n")
        buf.write("\n")

    for name, sub_model, _ in sub_sections:
        _render_section_table(buf, sub_model, f"{prefix}{name}.", heading_level=heading_level + 1)


def _render_top_level_table(
    buf: io.StringIO,
    model_class: type[BaseModel],
) -> None:
    """Render tables for all sections of a top-level model."""
    # First, collect top-level leaf fields
    leaf_fields: list[tuple[str, FieldInfo]] = []
    sections: list[tuple[str, type[BaseModel], FieldInfo]] = []

    for name, field_info in model_class.model_fields.items():
        if _is_section_field(field_info):
            sections.append((name, field_info.annotation, field_info))
        else:
            leaf_fields.append((name, field_info))

    if leaf_fields:
        buf.write("### Top-level keys\n\n")
        buf.write("| Key | Type | Default | Description |\n")
        buf.write("|-----|------|---------|-------------|\n")
        for name, fi in leaf_fields:
            type_s = _type_str(fi)
            default_s = _default_repr(fi)
            desc = _FIELD_DOCS.get(name, fi.description or "")
            buf.write(f"| `{name}` | {type_s} | {default_s} | {desc} |\n")
        buf.write("\n")

    for name, sub_model, _ in sections:
        _render_section_table(buf, sub_model, f"{name}.")


def _write_yaml_leaf(
    buf: io.StringIO, pad: str, name: str, field_info: FieldInfo, desc: str
) -> None:
    """Write a single commented-out leaf field to the YAML example."""
    if desc:
        buf.write(f"{pad}# {_strip_rst(desc)}\n")
    default = _yaml_default(field_info)
    buf.write(f"{pad}# {name}: {default}\n" if default else f"{pad}# {name}:\n")


def _render_yaml_example_with_prefix(
    buf: io.StringIO,
    model_class: type[BaseModel],
    prefix_path: str = "",
    *,
    indent: int = 0,
) -> None:
    """Render a full commented YAML example, using dotpath for doc lookup."""
    pad = "  " * indent
    for name, field_info in model_class.model_fields.items():
        dotpath = f"{prefix_path}.{name}" if prefix_path else name
        desc = _FIELD_DOCS.get(dotpath, field_info.description or "")

        if _is_section_field(field_info):
            if desc:
                buf.write(f"{pad}# {_strip_rst(desc)}\n")
            buf.write(f"{pad}{name}:\n")
            _render_yaml_example_with_prefix(
                buf, field_info.annotation, prefix_path=dotpath, indent=indent + 1
            )
            buf.write("\n")
        else:
            _write_yaml_leaf(buf, pad, name, field_info, desc)


def _strip_rst(text: str) -> str:
    """Strip RST/Markdown inline markup for YAML comments."""
    return text.replace("``", "").replace("**", "")


# ---------------------------------------------------------------------------
# Main: assemble the page
# ---------------------------------------------------------------------------


def _generate() -> str:
    """Generate the full config-reference.md content."""
    buf = io.StringIO()
    buf.write("# Configuration Reference\n\n")
    buf.write(
        "This page is **auto-generated** from the Pydantic schema models in "
        "[`yaml_schema.py`][terok.lib.core.yaml_schema].  "
        "Every field listed here is validated at load time — unknown keys are rejected, "
        "catching typos before they silently do nothing.\n\n"
    )

    buf.write(
        "**JSON Schema files** (for editor autocompletion and validation):\n"
        "[:material-download: project.schema.json](schemas/project.schema.json){: .md-button }\n"
        "[:material-download: config.schema.json](schemas/config.schema.json){: .md-button }\n\n"
    )

    # --- project.yml ---
    buf.write(_MD_RULE)
    buf.write("## project.yml\n\n")
    buf.write(
        "Per-project configuration.  Located at "
        "`<projects-root>/<id>/project.yml`, where the projects root is "
        "discovered via `user_projects_root()` (default "
        "`~/.config/terok/projects`, overridable via `paths.user_projects_root` "
        "in config.yml) or the system config root.\n\n"
    )

    _render_top_level_table(buf, RawProjectYaml)

    buf.write("### Full example\n\n")
    buf.write('```yaml title="project.yml"\n')
    _render_yaml_example_with_prefix(buf, RawProjectYaml)
    buf.write("```\n\n")

    # --- config.yml ---
    buf.write(_MD_RULE)
    buf.write("## config.yml\n\n")
    buf.write(
        "Global configuration.  Search order:\n\n"
        "1. `$TEROK_CONFIG_FILE` (explicit override)\n"
        "2. `${XDG_CONFIG_HOME:-~/.config}/terok/config.yml`\n"
        "3. `sys.prefix/etc/terok/config.yml`\n"
        "4. `/etc/terok/config.yml`\n\n"
    )

    _render_top_level_table(buf, RawGlobalConfig)

    buf.write("### Full example\n\n")
    buf.write('```yaml title="config.yml"\n')
    _render_yaml_example_with_prefix(buf, RawGlobalConfig)
    buf.write("```\n\n")

    # --- Validation ---
    buf.write(_MD_RULE)
    buf.write("## Validation behavior\n\n")
    buf.write(
        'All config models use Pydantic v2 with `extra="forbid"`.  This means:\n\n'
        "- **Typos are caught at load time** — e.g. `projecct:` instead of `project:` "
        "produces a clear error with the field path.\n"
        '- **Type mismatches are reported** — e.g. `shutdown_timeout: "ten"` fails '
        "with a descriptive message.\n"
        "- **Enum values are validated** — `security_class` must be `online` or `gatekeeping`.\n"
        "- **Null sections get defaults** — writing `git:` with no sub-keys is equivalent "
        "to omitting the section entirely.\n\n"
        "!!! note\n"
        "    **project.yml** validation is strict: errors produce a clear message and "
        "abort the operation.  **config.yml** validation is lenient: errors are logged "
        "as warnings and the file falls back to defaults, so a typo in global config "
        "never prevents the TUI or CLI from starting.\n"
    )

    return buf.getvalue()


_SCHEMAS: dict[str, type[BaseModel]] = {
    "project.schema.json": RawProjectYaml,
    "config.schema.json": RawGlobalConfig,
}

with mkdocs_gen_files.open("config-reference.md", "w") as f:
    f.write(_generate())

_SCHEMA_TITLES: dict[str, str] = {
    "project.schema.json": "terok project.yml",
    "config.schema.json": "terok config.yml",
}

for filename, model in _SCHEMAS.items():
    schema = model.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = _SCHEMA_TITLES.get(filename, schema.get("title", ""))
    with mkdocs_gen_files.open(f"schemas/{filename}", "w") as f:
        f.write(json.dumps(schema, indent=2) + "\n")
