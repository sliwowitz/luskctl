# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Curated egress allowlist sets — the shield's default t40 content.

Named bundles of well-known development endpoints a task can be granted at
MID granularity: coarse enough that a user picks a handful of named sets
instead of authoring host lists, fine enough that a Python-only project
doesn't drag in container registries.  The selection feeds the authored
t40 project-allow tier (ordinary allows — a security-deny always wins),
alongside the project's git remote host and its custom ``shield.allow``.

Ownership per the layering: terok owns the curated *workflow* content
here; the ``os-packages`` set alone resolves through terok-executor's
``package_repo_hosts`` — which distro repos a task needs is image
knowledge, keyed on the project's detected package family.

The **generous default** is every curated set: under a shield-up posture
the common workflows (git, language package managers, container pulls,
OS packages) must keep working out of the box.  Projects narrow the
selection via ``shield.sets`` in ``project.yml`` (the TUI chooser or
``terok shield sets`` write it); an explicit empty list disables all
curated content.
"""

from __future__ import annotations

from collections.abc import Iterable

OS_PACKAGES_SET = "os-packages"
"""The one dynamic set: distro package repos, resolved by package family."""

OS_PACKAGES_SUMMARY = "distro repos, resolved by the image's package family"
"""What to show operators in place of a host list for the dynamic set."""

EGRESS_SETS: dict[str, tuple[str, ...]] = {
    "git-hosting": (
        "github.com",
        "codeload.github.com",
        "objects.githubusercontent.com",
        "raw.githubusercontent.com",
        "gist.github.com",
        "gitlab.com",
        "bitbucket.org",
        "codeberg.org",
    ),
    "python": (
        "pypi.org",
        "files.pythonhosted.org",
    ),
    "node": (
        "registry.npmjs.org",
        "registry.yarnpkg.com",
        "nodejs.org",
    ),
    "rust": (
        "crates.io",
        "static.crates.io",
        "index.crates.io",
        "static.rust-lang.org",
    ),
    "go": (
        "proxy.golang.org",
        "sum.golang.org",
        "index.golang.org",
    ),
    "containers": (
        "registry-1.docker.io",
        "auth.docker.io",
        "index.docker.io",
        "production.cloudflare.docker.com",
        "quay.io",
        "cdn.quay.io",
        "cdn01.quay.io",
        "cdn02.quay.io",
        "cdn03.quay.io",
        "ghcr.io",
        "pkg-containers.githubusercontent.com",
        "registry.fedoraproject.org",
    ),
    OS_PACKAGES_SET: (),  # resolved dynamically — see resolve_egress_sets
}
"""Registry of curated sets: name → static hosts (``os-packages`` is dynamic)."""

DEFAULT_EGRESS_SETS: tuple[str, ...] = tuple(EGRESS_SETS)
"""The generous default: every curated set (applied when ``shield.sets`` is unset)."""


def selected_egress_sets(names: tuple[str, ...] | None) -> tuple[str, ...]:
    """The sets a ``shield.sets`` value actually grants (``None`` → the generous default)."""
    return DEFAULT_EGRESS_SETS if names is None else names


def describe_egress_sets(names: tuple[str, ...] | None) -> str:
    """Render a ``shield.sets`` value for an operator — one wording, every surface."""
    if names is None:
        return "default (all curated sets)"
    return ", ".join(names) or "none (curated content disabled)"


def validate_egress_sets(names: Iterable[str] | None) -> None:
    """Reject unknown set names with the available registry spelled out.

    Called at project-load time so a typo in ``shield.sets`` fails the
    load loudly instead of silently granting nothing.
    """
    if names is None:
        return
    unknown = [n for n in names if n not in EGRESS_SETS]
    if unknown:
        raise SystemExit(
            f"Unknown shield.sets entr{'ies' if len(unknown) > 1 else 'y'}: "
            f"{', '.join(map(repr, unknown))}.  Available sets: {', '.join(EGRESS_SETS)}"
        )


def resolve_egress_sets(names: tuple[str, ...] | None, family: str | None) -> tuple[str, ...]:
    """Resolve a set selection into its hosts (order-preserving, de-duplicated).

    *names* is the project's ``shield.sets`` — ``None`` applies the
    generous default (every set), an empty tuple resolves to nothing.
    *family* is the project image's package family (``deb``/``rpm``/None),
    consumed by the ``os-packages`` set through terok-executor's
    ``package_repo_hosts``; an unrecognized image gets the generous
    all-family union.
    """
    from terok.lib.integrations.executor import package_repo_hosts

    hosts: list[str] = []
    for name in selected_egress_sets(names):
        hosts += package_repo_hosts(family) if name == OS_PACKAGES_SET else EGRESS_SETS[name]
    return tuple(dict.fromkeys(hosts))
