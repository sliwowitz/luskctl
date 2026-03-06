# SPDX-FileCopyrightText: 2025-2026 Jiri Vyskocil <jiri@vyskocil.com>
#
# SPDX-License-Identifier: Apache-2.0

"""Podman user-namespace and network helpers for rootless operation."""

import functools
import json
import os
import subprocess


def _podman_userns_args() -> list[str]:
    """Return user namespace args for rootless podman so UID 1000 maps correctly."""
    if os.geteuid() == 0:
        return []
    return ["--userns=keep-id:uid=1000,gid=1000"]


@functools.lru_cache(maxsize=1)
def _detect_rootless_network_mode() -> str:
    """Return ``"slirp4netns"``, ``"pasta"``, or ``"unknown"`` from ``podman info``.

    Reads ``host.rootlessNetworkCmd`` (present on Podman 4.x and 5.x).
    Falls back to ``host.networkBackend`` — ``"netavark"`` implies pasta
    (Podman 5+ default).  On error returns ``"unknown"``.
    """
    try:
        raw = subprocess.check_output(
            ["podman", "info", "-f", "json"],
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        info = json.loads(raw)
        host = info.get("host", {})

        # Primary: rootlessNetworkCmd is set on both Podman 4.x and 5.x
        cmd = host.get("rootlessNetworkCmd", "")
        if cmd in ("pasta", "slirp4netns"):
            return cmd

        # Fallback: netavark backend implies pasta (Podman 5+ default)
        if host.get("networkBackend") == "netavark":
            return "pasta"

        return "unknown"
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        TypeError,
        ValueError,
    ):
        return "unknown"


def _podman_network_args() -> list[str]:
    """Return network flags so rootless containers can reach host loopback.

    On slirp4netns (Podman 4.x), the container's default gateway ``10.0.2.2``
    is routed to the host's ``127.0.0.1`` when ``allow_host_loopback=true`` is
    set.  Combined with ``--add-host host.containers.internal:10.0.2.2``, the
    existing ``git://host.containers.internal:...`` URLs work without changes.

    On pasta (Podman 5+), ``host.containers.internal`` already routes to
    loopback.  No extra flags needed.
    """
    if os.geteuid() == 0:
        return []

    mode = _detect_rootless_network_mode()
    if mode == "slirp4netns":
        return [
            "--network",
            "slirp4netns:allow_host_loopback=true",
            "--add-host",
            "host.containers.internal:10.0.2.2",
        ]
    return []
