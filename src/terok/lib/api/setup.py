# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""First-run setup, env check, sandbox-uninstall, sickbay primitives — public API surface.

Re-export catalog for the host-side bootstrap pieces (and the sickbay
diagnostic surface that lives on top of them).  Source:
[`terok.lib.integrations.sandbox`][terok.lib.integrations.sandbox] —
terok-sandbox owns the bootstrap logic; terok presents it.  The
``namespace_state_dir`` path resolver flows from
[`terok_util`][terok_util] — the foundation library — not through the
sandbox adapter.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from terok_util import (
        namespace_state_dir as namespace_state_dir,
    )

    from terok.lib.integrations.sandbox import (
        BUNDLE_VERSION as BUNDLE_VERSION,
        EXIT_MANUAL_STEP_NEEDED as EXIT_MANUAL_STEP_NEEDED,
        SERVICES_TCP_OPTOUT_YAML as SERVICES_TCP_OPTOUT_YAML,
        SETUP_COMPONENTS as SETUP_COMPONENTS,
        EnvironmentCheck as EnvironmentCheck,
        SelinuxStatus as SelinuxStatus,
        SetupVerdict as SetupVerdict,
        ShieldAnnotations as ShieldAnnotations,
        ShieldHooks as ShieldHooks,
        check_environment as check_environment,
        check_selinux_status as check_selinux_status,
        handle_setup_component as handle_setup_component,
        is_ssh_url as is_ssh_url,
        make_kernel_keyring_quota_check as make_kernel_keyring_quota_check,
        needs_setup as needs_setup,
        public_line_of as public_line_of,
        resolve_container_annotations as resolve_container_annotations,
        resolve_container_shield_version as resolve_container_shield_version,
        resolve_container_state_dir as resolve_container_state_dir,
        sandbox_uninstall as sandbox_uninstall,
        selinux_install_script as selinux_install_script,
        systemd_creds_has_tpm2 as systemd_creds_has_tpm2,
        yaml_update_section as yaml_update_section,
    )

#: Public name -> defining module (PEP 562 lazy resolution).
_LAZY: dict[str, str] = {
    "EnvironmentCheck": "terok.lib.integrations.sandbox",
    "SERVICES_TCP_OPTOUT_YAML": "terok.lib.integrations.sandbox",
    "SelinuxStatus": "terok.lib.integrations.sandbox",
    "SetupVerdict": "terok.lib.integrations.sandbox",
    "ShieldHooks": "terok.lib.integrations.sandbox",
    "check_environment": "terok.lib.integrations.sandbox",
    "make_kernel_keyring_quota_check": "terok.lib.integrations.sandbox",
    "EXIT_MANUAL_STEP_NEEDED": "terok.lib.integrations.sandbox",
    "SETUP_COMPONENTS": "terok.lib.integrations.sandbox",
    "check_selinux_status": "terok.lib.integrations.sandbox",
    "handle_setup_component": "terok.lib.integrations.sandbox",
    "is_ssh_url": "terok.lib.integrations.sandbox",
    "namespace_state_dir": "terok_util",
    "needs_setup": "terok.lib.integrations.sandbox",
    "public_line_of": "terok.lib.integrations.sandbox",
    "BUNDLE_VERSION": "terok.lib.integrations.sandbox",
    "ShieldAnnotations": "terok.lib.integrations.sandbox",
    "resolve_container_annotations": "terok.lib.integrations.sandbox",
    "resolve_container_shield_version": "terok.lib.integrations.sandbox",
    "resolve_container_state_dir": "terok.lib.integrations.sandbox",
    "sandbox_uninstall": "terok.lib.integrations.sandbox",
    "selinux_install_script": "terok.lib.integrations.sandbox",
    "systemd_creds_has_tpm2": "terok.lib.integrations.sandbox",
    "yaml_update_section": "terok.lib.integrations.sandbox",
}

__all__ = [
    "EnvironmentCheck",
    "SERVICES_TCP_OPTOUT_YAML",
    "SelinuxStatus",
    "SetupVerdict",
    "ShieldHooks",
    "check_environment",
    "make_kernel_keyring_quota_check",
    "EXIT_MANUAL_STEP_NEEDED",
    "SETUP_COMPONENTS",
    "check_selinux_status",
    "handle_setup_component",
    "is_ssh_url",
    "needs_setup",
    "public_line_of",
    "BUNDLE_VERSION",
    "ShieldAnnotations",
    "resolve_container_annotations",
    "resolve_container_shield_version",
    "resolve_container_state_dir",
    "sandbox_uninstall",
    "selinux_install_script",
    "systemd_creds_has_tpm2",
    "yaml_update_section",
]


def __getattr__(name: str) -> object:
    """Resolve a re-exported name to its source module on first access (PEP 562)."""
    try:
        target = _LAZY[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    module_path, _, source_name = target.partition(":")
    value = getattr(importlib.import_module(module_path), source_name or name)
    globals()[name] = value  # cache so subsequent lookups skip __getattr__
    return value


def __dir__() -> list[str]:
    """Expose the lazy names to ``dir()`` / autocompletion."""
    return sorted({*globals(), *_LAZY})
