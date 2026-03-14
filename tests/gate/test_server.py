# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Tests for the standalone gate HTTP server."""

import base64
import io
import json
import tempfile
import unittest.mock
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from terok.gate.server import (
    _ROUTE,
    TokenStore,
    _extract_basic_auth_token,
    _make_handler_class,
    _parse_cgi_headers,
    _parse_content_length,
    _validate_token_data,
)
from testnet import GATE_PORT, LOCALHOST_PEER


class TestTokenStore:
    """Tests for TokenStore."""

    def test_validate_valid_token(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tf = Path(td) / "tokens.json"
            tf.write_text(json.dumps({"abc123": {"project": "proj-a", "task": "1"}}))
            store = TokenStore(tf)
            assert store.validate("abc123") == "proj-a"

    def test_validate_invalid_token(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tf = Path(td) / "tokens.json"
            tf.write_text(json.dumps({"abc123": {"project": "proj-a", "task": "1"}}))
            store = TokenStore(tf)
            assert store.validate("wrong") is None

    def test_missing_file_returns_none(self) -> None:
        store = TokenStore(Path("/nonexistent/tokens.json"))
        assert store.validate("any") is None

    def test_corrupt_json_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tf = Path(td) / "tokens.json"
            tf.write_text("not json{{{")
            store = TokenStore(tf)
            assert store.validate("any") is None

    def test_mtime_reload(self) -> None:
        """Token store reloads when file mtime changes."""
        with tempfile.TemporaryDirectory() as td:
            tf = Path(td) / "tokens.json"
            tf.write_text(json.dumps({"t1": {"project": "p1", "task": "1"}}))
            store = TokenStore(tf)
            assert store.validate("t1") == "p1"

            # Overwrite with new token (force different mtime)
            import os
            import time

            time.sleep(0.05)
            tf.write_text(json.dumps({"t2": {"project": "p2", "task": "2"}}))
            # Force mtime change
            st = tf.stat()
            os.utime(tf, (st.st_atime, st.st_mtime + 1))

            assert store.validate("t1") is None
            assert store.validate("t2") == "p2"

    def test_malformed_token_entry_skipped(self) -> None:
        """Token entries with wrong structure are ignored."""
        with tempfile.TemporaryDirectory() as td:
            tf = Path(td) / "tokens.json"
            tf.write_text(json.dumps({"bad": "not-a-dict", "ok": {"project": "p", "task": "1"}}))
            store = TokenStore(tf)
            assert store.validate("bad") is None
            assert store.validate("ok") == "p"

    def test_non_dict_json_returns_none(self) -> None:
        """Non-dict top-level JSON is treated as empty."""
        with tempfile.TemporaryDirectory() as td:
            tf = Path(td) / "tokens.json"
            tf.write_text(json.dumps(["a", "b"]))
            store = TokenStore(tf)
            assert store.validate("a") is None


class TestValidateTokenData:
    """Tests for _validate_token_data."""

    def test_valid_data(self) -> None:
        data = {"t1": {"project": "p", "task": "1"}}
        assert _validate_token_data(data) == data

    def test_non_dict_returns_empty(self) -> None:
        assert _validate_token_data([1, 2]) == {}
        assert _validate_token_data("string") == {}

    def test_skips_non_dict_values(self) -> None:
        data = {"good": {"project": "p", "task": "1"}, "bad": "string"}
        result = _validate_token_data(data)
        assert len(result) == 1
        assert "good" in result

    def test_skips_missing_fields(self) -> None:
        data = {"no_task": {"project": "p"}, "no_proj": {"task": "1"}}
        assert _validate_token_data(data) == {}


class TestExtractBasicAuthToken:
    """Tests for _extract_basic_auth_token."""

    def test_valid_basic_auth(self) -> None:
        creds = base64.b64encode(b"mytoken:password").decode()
        assert _extract_basic_auth_token(f"Basic {creds}") == "mytoken"

    def test_none_header(self) -> None:
        assert _extract_basic_auth_token(None) is None

    def test_non_basic_scheme(self) -> None:
        assert _extract_basic_auth_token("Bearer xyz") is None

    def test_invalid_base64(self) -> None:
        assert _extract_basic_auth_token("Basic !!!") is None

    def test_no_colon(self) -> None:
        creds = base64.b64encode(b"nocolon").decode()
        assert _extract_basic_auth_token(f"Basic {creds}") is None

    def test_empty_username(self) -> None:
        creds = base64.b64encode(b":password").decode()
        assert _extract_basic_auth_token(f"Basic {creds}") is None


class TestParseContentLength:
    """Tests for _parse_content_length."""

    def test_valid_length(self) -> None:
        length, err = _parse_content_length("42")
        assert length == 42
        assert err is None

    def test_none_header(self) -> None:
        length, err = _parse_content_length(None)
        assert length == 0
        assert err is None

    def test_negative(self) -> None:
        _, err = _parse_content_length("-5")
        assert err is not None

    def test_non_numeric(self) -> None:
        _, err = _parse_content_length("abc")
        assert err is not None


class TestParseCgiHeaders:
    """Tests for _parse_cgi_headers."""

    def test_parses_status_and_headers(self) -> None:
        stdout = io.BytesIO(b"Status: 404 Not Found\r\nContent-Type: text/plain\r\n\r\nbody")
        status, headers = _parse_cgi_headers(stdout)
        assert status == 404
        assert headers == [("Content-Type", "text/plain")]

    def test_defaults_to_200(self) -> None:
        stdout = io.BytesIO(b"Content-Type: text/html\r\n\r\n")
        status, _ = _parse_cgi_headers(stdout)
        assert status == 200

    def test_empty_response(self) -> None:
        stdout = io.BytesIO(b"\r\n")
        status, headers = _parse_cgi_headers(stdout)
        assert status == 200
        assert headers == []


class TestRouting:
    """Tests for the route regex."""

    def test_info_refs(self) -> None:
        m = _ROUTE.match("/proj-a.git/info/refs")
        assert m is not None
        assert m.group("repo") == "proj-a.git"
        assert m.group("path") == "/info/refs"

    def test_upload_pack(self) -> None:
        m = _ROUTE.match("/proj-a.git/git-upload-pack")
        assert m is not None

    def test_receive_pack(self) -> None:
        m = _ROUTE.match("/proj-a.git/git-receive-pack")
        assert m is not None

    def test_head(self) -> None:
        m = _ROUTE.match("/proj-a.git/HEAD")
        assert m is not None

    def test_invalid_path_returns_none(self) -> None:
        assert _ROUTE.match("/proj-a.git/objects/pack/pack-abc.pack") is None
        assert _ROUTE.match("/some/random/path") is None
        assert _ROUTE.match("/") is None

    def test_repo_without_git_suffix_fails(self) -> None:
        assert _ROUTE.match("/proj-a/info/refs") is None


class _FakeSocket:
    """Minimal socket-like object for testing."""

    def __init__(self, request_bytes: bytes) -> None:
        self._input = io.BytesIO(request_bytes)
        self._output = io.BytesIO()

    def makefile(self, mode: str, buffering: int = -1) -> io.BytesIO:
        """Return a file-like object for reading or writing."""
        if "r" in mode:
            return self._input
        return self._output

    def getpeername(self) -> tuple[str, int]:
        """Return a fake peer address."""
        return LOCALHOST_PEER

    def close(self) -> None:
        """No-op close."""


class TestAuth:
    """Tests for authentication handling."""

    def _make_request(
        self,
        path: str,
        token: str | None = None,
        method: str = "GET",
        extra_headers: str = "",
    ) -> tuple[int, BaseHTTPRequestHandler]:
        """Build a fake HTTP request and return (status_code, handler)."""
        with tempfile.TemporaryDirectory() as td:
            tf = Path(td) / "tokens.json"
            tf.write_text(json.dumps({"validtoken": {"project": "proj-a", "task": "1"}}))
            store = TokenStore(tf)
            handler_class = _make_handler_class(Path(td), store)

            headers = "Host: localhost\r\n"
            if token is not None:
                creds = base64.b64encode(f"{token}:x".encode()).decode()
                headers += f"Authorization: Basic {creds}\r\n"
            headers += extra_headers

            raw_request = f"{method} {path} HTTP/1.1\r\n{headers}\r\n".encode()

            # Create a mock handler to capture the response
            handler = handler_class.__new__(handler_class)
            handler.request = None
            handler.client_address = LOCALHOST_PEER
            handler.server = type(
                "FakeServer", (), {"server_name": "localhost", "server_port": GATE_PORT}
            )()
            handler.rfile = io.BytesIO(raw_request)
            handler.wfile = io.BytesIO()
            handler.raw_requestline = handler.rfile.readline(65537)
            handler.parse_request()

            # Capture send_response calls
            responses = []
            original_send_response = handler.send_response

            def capture_response(code, *args):
                responses.append(code)
                original_send_response(code, *args)

            handler.send_response = capture_response
            handler.send_error = lambda code, *args: responses.append(code)

            handler._handle()
            return responses[0] if responses else 0, handler

    def test_no_auth_returns_401(self) -> None:
        code, _ = self._make_request("/proj-a.git/info/refs", token=None)
        assert code == 401

    def test_wrong_token_returns_403(self) -> None:
        code, _ = self._make_request("/proj-a.git/info/refs", token="wrongtoken")
        assert code == 403

    def test_wrong_project_returns_403(self) -> None:
        code, _ = self._make_request("/proj-b.git/info/refs", token="validtoken")
        assert code == 403

    def test_invalid_path_returns_404(self) -> None:
        code, _ = self._make_request("/invalid/path", token="validtoken")
        assert code == 404

    @unittest.mock.patch("subprocess.Popen")
    def test_valid_auth_delegates_to_cgi(self, mock_popen: unittest.mock.Mock) -> None:
        """Valid token + matching project delegates to git http-backend."""
        # Mock the subprocess to avoid needing real git
        mock_proc = unittest.mock.Mock()
        mock_proc.stdin = io.BytesIO()
        mock_proc.stdout = io.BytesIO(b"Status: 200 OK\r\nContent-Type: text/plain\r\n\r\nok")
        mock_proc.stderr = io.BytesIO(b"")
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        code, _ = self._make_request(
            "/proj-a.git/info/refs?service=git-upload-pack", token="validtoken"
        )
        assert code == 200
        mock_popen.assert_called_once()
        # Verify CGI env includes GIT_PROJECT_ROOT
        call_kwargs = mock_popen.call_args
        cgi_env = call_kwargs[1]["env"]
        assert "GIT_PROJECT_ROOT" in cgi_env
        assert cgi_env["GIT_HTTP_EXPORT_ALL"] == "1"
        # Defense in depth: hooks disabled
        assert cgi_env["GIT_CONFIG_KEY_0"] == "core.hooksPath"
        assert cgi_env["GIT_CONFIG_VALUE_0"] == "/dev/null"

    @unittest.mock.patch("terok.gate.server._logger")
    @unittest.mock.patch("subprocess.Popen")
    def test_cgi_stderr_is_logged(
        self, mock_popen: unittest.mock.Mock, mock_logger: unittest.mock.Mock
    ) -> None:
        """CGI stderr output is logged via the module logger."""
        mock_proc = unittest.mock.Mock()
        mock_proc.stdin = io.BytesIO()
        mock_proc.stdout = io.BytesIO(b"Status: 200 OK\r\n\r\n")
        mock_proc.stderr = io.BytesIO(b"warning: something happened")
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        code, _ = self._make_request(
            "/proj-a.git/info/refs?service=git-upload-pack", token="validtoken"
        )
        assert code == 200
        mock_logger.warning.assert_called_once()
        logged_msg = mock_logger.warning.call_args[0][1]
        assert "something happened" in logged_msg

    def test_invalid_content_length_returns_400(self) -> None:
        """Malformed Content-Length header returns 400."""
        code, _ = self._make_request(
            "/proj-a.git/git-receive-pack",
            token="validtoken",
            method="POST",
            extra_headers="Content-Length: notanumber\r\n",
        )
        assert code == 400

    def test_negative_content_length_returns_400(self) -> None:
        """Negative Content-Length header returns 400."""
        code, _ = self._make_request(
            "/proj-a.git/git-receive-pack",
            token="validtoken",
            method="POST",
            extra_headers="Content-Length: -5\r\n",
        )
        assert code == 400

    @unittest.mock.patch("subprocess.Popen")
    def test_content_encoding_forwarded(self, mock_popen: unittest.mock.Mock) -> None:
        """Content-Encoding header is forwarded as HTTP_CONTENT_ENCODING."""
        mock_proc = unittest.mock.Mock()
        mock_proc.stdin = io.BytesIO()
        mock_proc.stdout = io.BytesIO(b"Status: 200 OK\r\n\r\n")
        mock_proc.stderr = io.BytesIO(b"")
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        code, _ = self._make_request(
            "/proj-a.git/git-upload-pack",
            token="validtoken",
            method="POST",
            extra_headers="Content-Encoding: gzip\r\nContent-Length: 0\r\n",
        )
        assert code == 200
        cgi_env = mock_popen.call_args[1]["env"]
        assert cgi_env["HTTP_CONTENT_ENCODING"] == "gzip"

    @unittest.mock.patch("subprocess.Popen")
    def test_git_protocol_forwarded(self, mock_popen: unittest.mock.Mock) -> None:
        """Git-Protocol header is forwarded as HTTP_GIT_PROTOCOL."""
        mock_proc = unittest.mock.Mock()
        mock_proc.stdin = io.BytesIO()
        mock_proc.stdout = io.BytesIO(b"Status: 200 OK\r\n\r\n")
        mock_proc.stderr = io.BytesIO(b"")
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        code, _ = self._make_request(
            "/proj-a.git/info/refs?service=git-upload-pack",
            token="validtoken",
            extra_headers="Git-Protocol: version=2\r\n",
        )
        assert code == 200
        cgi_env = mock_popen.call_args[1]["env"]
        assert cgi_env["HTTP_GIT_PROTOCOL"] == "version=2"

    @unittest.mock.patch("subprocess.Popen")
    def test_absent_headers_not_in_env(self, mock_popen: unittest.mock.Mock) -> None:
        """Absent Content-Encoding/Git-Protocol headers are not set in CGI env."""
        mock_proc = unittest.mock.Mock()
        mock_proc.stdin = io.BytesIO()
        mock_proc.stdout = io.BytesIO(b"Status: 200 OK\r\n\r\n")
        mock_proc.stderr = io.BytesIO(b"")
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc

        code, _ = self._make_request(
            "/proj-a.git/info/refs?service=git-upload-pack", token="validtoken"
        )
        assert code == 200
        cgi_env = mock_popen.call_args[1]["env"]
        assert "HTTP_CONTENT_ENCODING" not in cgi_env
        assert "HTTP_GIT_PROTOCOL" not in cgi_env


class TestDetach:
    """Tests for daemon (detach) mode."""

    def test_child_calls_serve_forever(self) -> None:
        """Child process (fork returns 0) should call serve_forever."""
        from terok.gate.server import _serve_daemon

        with tempfile.TemporaryDirectory() as td:
            mock_server = unittest.mock.Mock()
            mock_server.serve_forever.side_effect = SystemExit(0)

            with (
                unittest.mock.patch(
                    "terok.gate.server._ThreadingHTTPServer", return_value=mock_server
                ),
                unittest.mock.patch("terok.gate.server.os.fork", return_value=0),
                unittest.mock.patch("terok.gate.server.signal.signal") as mock_signal,
                unittest.mock.patch("terok.gate.server.os.setsid") as mock_setsid,
                unittest.mock.patch("terok.gate.server.os.open", return_value=3),
                unittest.mock.patch("terok.gate.server.os.dup2"),
                unittest.mock.patch("terok.gate.server.os.close"),
            ):
                store = TokenStore(Path(td) / "tokens.json")
                with pytest.raises(SystemExit):
                    _serve_daemon(Path(td), store, 9418, None)

                mock_setsid.assert_called_once()
                mock_signal.assert_called_once()
                mock_server.serve_forever.assert_called_once()

    @unittest.mock.patch("terok.gate.server._ThreadingHTTPServer")
    @unittest.mock.patch("terok.gate.server.os.fork", return_value=42)
    def test_parent_writes_pid_file(
        self, mock_fork: unittest.mock.Mock, mock_server_class: unittest.mock.Mock
    ) -> None:
        """Parent process (fork returns child PID) should write PID file and exit."""
        from terok.gate.server import _serve_daemon

        with tempfile.TemporaryDirectory() as td:
            pid_file = Path(td) / "gate.pid"
            store = TokenStore(Path(td) / "tokens.json")
            with pytest.raises(SystemExit):
                _serve_daemon(Path(td), store, 9418, pid_file)
            assert pid_file.read_text() == "42"
