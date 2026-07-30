# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Story: the agent inside a task container gets a *coherent* reply from "something".

[`test_phantom_token_roundtrip`][tests.integration.stories.test_phantom_token_roundtrip]
proves the phantom→real swap happens and that the phantom never leaks.  These two
add the agent's-eye view that a mock upstream makes cheap to assert without real API
keys: the container reaches the vault over its bind-mounted socket and gets back a
reply it can actually parse, and a request *body* it sends survives the broker hop
intact.  Together they simulate "the agent can talk to something that answers
sensibly" — the whole point of pointing the host side of the vault at a mock.

Both reuse the ``running_token_broker_socket`` + ``mock_upstream_api`` fixtures (the
mock echoes a structured JSON reply and records every request), so the only new
surface is the in-container ``curl`` and the assertions on what came back.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import uuid

import pytest

from tests.integration.helpers import (
    PODMAN_CONTAINER_PREFIX,
    PODMAN_TEST_IMAGE,
    podman_subprocess_env as _podman_env,
)
from tests.integration.stories.conftest import MockUpstreamState, VaultSocketEnv

# Every story here talks to a real DB + broker, and drives a real container.
pytestmark = [pytest.mark.needs_vault, pytest.mark.needs_podman]


def _qualified_image() -> str:
    """Return the local-store-qualified test image reference (see roundtrip story)."""
    return PODMAN_TEST_IMAGE if "/" in PODMAN_TEST_IMAGE else f"localhost/{PODMAN_TEST_IMAGE}"


async def _run_container(name: str, host_socket: str) -> None:
    """Start a keepalive container with the broker socket bind-mounted at ``/vault.sock``."""
    result = await asyncio.to_thread(
        subprocess.run,
        [
            "podman", "run", "-d", "--rm",
            "--pull", "never",
            "--security-opt", "label=disable",
            "--name", name,
            "-v", f"{host_socket}:/vault.sock",
            _qualified_image(),
            "sleep", "60",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=_podman_env(),
    )  # fmt: skip
    assert result.returncode == 0, (
        f"podman run failed (exit {result.returncode}):\n"
        f"  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}"
    )


async def _exec(name: str, *argv: str, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    """Run ``podman exec <name> <argv>`` off-thread so the broker keeps servicing."""
    return await asyncio.to_thread(
        subprocess.run,
        ["podman", "exec", name, *argv],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_podman_env(),
    )


async def test_container_receives_coherent_json_reply_through_socket(
    running_token_broker_socket: VaultSocketEnv,
    mock_upstream_api: MockUpstreamState,
    _pull_image: None,
) -> None:
    """The container's ``curl`` gets back a parseable reply reflecting the real swap.

    The existing roundtrip story asserts the *upstream* saw the real key; this asserts
    the other direction — that the reply the mock produced actually reaches the agent
    inside the container and is coherent JSON it could act on.
    """
    if not shutil.which("podman"):
        pytest.skip("podman not on PATH")

    real_key = running_token_broker_socket.real_credential["key"]
    phantom = running_token_broker_socket.phantom_token
    host_socket = str(running_token_broker_socket.socket_path)
    name = f"{PODMAN_CONTAINER_PREFIX}-reply-{uuid.uuid4().hex[:8]}"

    try:
        await _run_container(name, host_socket)
        exec_result = await _exec(
            name,
            "curl", "-sS", "--fail",
            "--unix-socket", "/vault.sock",
            "-H", f"Authorization: Bearer {phantom}",
            "http://localhost/v1/messages",
        )  # fmt: skip
        assert exec_result.returncode == 0, (
            f"in-container curl failed (exit {exec_result.returncode}):\n"
            f"  stdout: {exec_result.stdout!r}\n  stderr: {exec_result.stderr!r}"
        )

        # The agent parses the reply — it must be coherent JSON, echo the path it
        # called, and reflect the *real* key the broker injected (never the phantom).
        reply = json.loads(exec_result.stdout)
        assert reply["path"] == "/v1/messages"
        assert reply["authorization"] == f"Bearer {real_key}"
        assert phantom not in exec_result.stdout
    finally:
        await asyncio.to_thread(
            subprocess.run,
            ["podman", "rm", "-f", name],
            capture_output=True,
            timeout=30,
            env=_podman_env(),
        )


async def test_request_body_survives_the_broker_hop_from_the_container(
    running_token_broker_socket: VaultSocketEnv,
    mock_upstream_api: MockUpstreamState,
    _pull_image: None,
) -> None:
    """A POST body sent from inside the container reaches the upstream byte-for-byte.

    The broker reads and re-streams the request body (``_handle_request``); this
    checks that path end-to-end over the real socket transport, not just in-process.
    """
    if not shutil.which("podman"):
        pytest.skip("podman not on PATH")

    phantom = running_token_broker_socket.phantom_token
    host_socket = str(running_token_broker_socket.socket_path)
    body = '{"model":"claude","messages":[{"role":"user","content":"hi"}]}'
    name = f"{PODMAN_CONTAINER_PREFIX}-body-{uuid.uuid4().hex[:8]}"

    try:
        await _run_container(name, host_socket)
        exec_result = await _exec(
            name,
            "curl", "-sS", "--fail",
            "--unix-socket", "/vault.sock",
            "-H", f"Authorization: Bearer {phantom}",
            "-H", "Content-Type: application/json",
            "--data-binary", body,
            "http://localhost/v1/messages",
        )  # fmt: skip
        assert exec_result.returncode == 0, (
            f"in-container curl failed (exit {exec_result.returncode}):\n"
            f"  stdout: {exec_result.stdout!r}\n  stderr: {exec_result.stderr!r}"
        )

        assert len(mock_upstream_api.requests) == 1
        captured = mock_upstream_api.last
        assert captured.method == "POST"
        assert captured.path == "/v1/messages"
        assert captured.body == body.encode(), "request body was mangled crossing the broker"
    finally:
        await asyncio.to_thread(
            subprocess.run,
            ["podman", "rm", "-f", name],
            capture_output=True,
            timeout=30,
            env=_podman_env(),
        )
