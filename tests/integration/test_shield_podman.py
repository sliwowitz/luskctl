# SPDX-FileCopyrightText: 2025 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Tier 2 integration tests: full end-to-end with real Podman.

These tests require ``podman`` on PATH and are auto-skipped when it
is absent. Some additionally require root for nftables operations.

Uses the per-task Shield class API.
"""

import pytest

terok_shield = pytest.importorskip("terok_shield")
Shield = terok_shield.Shield

from tests.testnet import ALLOWED_TARGET_DOMAIN, ALLOWED_TARGET_HTTP, TEST_IP_RFC5737

from .conftest import nft_missing, podman_missing, skip_if_no_root
from .helpers import assert_blocked, assert_reachable, inspect_container_json

pytestmark = pytest.mark.needs_podman


# ── TestShieldEndToEnd ───────────────────────────────────


@podman_missing
@nft_missing
class TestShieldEndToEnd:
    """End-to-end tests with a real container."""

    def test_container_starts_with_annotations(self, shielded_container: str) -> None:
        """Inspect container and verify shield annotations are present."""
        container_info = inspect_container_json(shielded_container)
        annotations = container_info.get("Config", {}).get("Annotations", {})
        assert "terok.shield.profiles" in annotations
        assert "dev-standard" in annotations["terok.shield.profiles"]

    @skip_if_no_root
    def test_shield_rules_returns_ruleset(
        self, shielded_container: str, real_shield: Shield
    ) -> None:
        """shield.rules returns a non-empty ruleset containing terok_shield."""
        output = real_shield.rules(shielded_container)
        assert "terok_shield" in output

    @skip_if_no_root
    def test_allow_then_deny(self, shielded_container: str, real_shield: Shield) -> None:
        """shield.allow adds an IP; shield.deny removes it."""
        allowed = real_shield.allow(shielded_container, TEST_IP_RFC5737)
        assert TEST_IP_RFC5737 in allowed
        rules_after_allow = real_shield.rules(shielded_container)
        assert TEST_IP_RFC5737 in rules_after_allow

        denied = real_shield.deny(shielded_container, TEST_IP_RFC5737)
        assert TEST_IP_RFC5737 in denied
        rules_after_deny = real_shield.rules(shielded_container)
        assert TEST_IP_RFC5737 not in rules_after_deny


# ── TestShieldEgress ──────────────────────────────────────


@podman_missing
@nft_missing
@skip_if_no_root
@pytest.mark.needs_internet
@pytest.mark.usefixtures("_verify_connectivity")
class TestShieldEgress:
    """Egress filtering tests (requires network + root)."""

    def test_egress_blocked_by_default(self, shielded_container: str) -> None:
        """Container cannot reach an external host by default."""
        assert_blocked(shielded_container, ALLOWED_TARGET_HTTP, timeout=5)

    def test_egress_allowed_after_allow(self, shielded_container: str, real_shield: Shield) -> None:
        """Container can reach a host after shield.allow."""
        real_shield.allow(shielded_container, ALLOWED_TARGET_DOMAIN)
        assert_reachable(shielded_container, ALLOWED_TARGET_HTTP, timeout=10)
