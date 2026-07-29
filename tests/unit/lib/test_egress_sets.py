# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Tests for the curated egress-set registry and its resolution."""

from __future__ import annotations

import pytest

from terok.lib.core.egress_sets import (
    DEFAULT_EGRESS_SETS,
    EGRESS_SETS,
    OS_PACKAGES_SET,
    resolve_egress_sets,
    validate_egress_sets,
)


def test_registry_shape() -> None:
    """Every static set carries hosts; only ``os-packages`` is dynamic (empty here)."""
    for name, hosts in EGRESS_SETS.items():
        assert name == name.lower()
        if name == OS_PACKAGES_SET:
            assert hosts == ()
        else:
            assert hosts, f"static set {name} has no hosts"
            assert len(hosts) == len(set(hosts)), f"duplicate hosts in {name}"


def test_default_is_every_set() -> None:
    """The generous default selects the whole registry, in registry order."""
    assert tuple(EGRESS_SETS) == DEFAULT_EGRESS_SETS


def test_validate_accepts_known_and_none() -> None:
    validate_egress_sets(None)
    validate_egress_sets(())
    validate_egress_sets(tuple(EGRESS_SETS))


def test_validate_rejects_unknown_with_available_names() -> None:
    """A typo fails loudly and spells out the registry."""
    with pytest.raises(SystemExit, match="Available sets"):
        validate_egress_sets(("pythn",))


def test_resolve_none_applies_generous_default() -> None:
    """``None`` resolves every set, including the family-resolved OS repos."""
    from terok.lib.integrations.executor import package_repo_hosts

    hosts = resolve_egress_sets(None, "deb")
    for name, static_hosts in EGRESS_SETS.items():
        if name != OS_PACKAGES_SET:
            assert set(static_hosts) <= set(hosts)
    assert set(package_repo_hosts("deb")) <= set(hosts)


def test_resolve_empty_disables_curated_content() -> None:
    assert resolve_egress_sets((), "rpm") == ()


def test_resolve_subset_is_exactly_its_hosts() -> None:
    name = next(n for n in EGRESS_SETS if n != OS_PACKAGES_SET)
    assert resolve_egress_sets((name,), None) == EGRESS_SETS[name]


def test_resolve_os_packages_follows_family() -> None:
    """The dynamic set delegates to executor's family-keyed repo data."""
    from terok.lib.integrations.executor import package_repo_hosts

    assert resolve_egress_sets((OS_PACKAGES_SET,), "rpm") == package_repo_hosts("rpm")
    # Unrecognized image → the generous all-family union.
    assert resolve_egress_sets((OS_PACKAGES_SET,), None) == package_repo_hosts(None)
