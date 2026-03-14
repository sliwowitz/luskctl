# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Tests for gate_server module."""

import contextlib
import os
import subprocess
import tempfile
import unittest.mock
from pathlib import Path

import pytest

from terok.lib.security.gate_server import (
    _UNIT_VERSION,
    GateServerStatus,
    _installed_unit_version,
    _is_managed_server,
    check_units_outdated,
    ensure_server_reachable,
    get_server_status,
    install_systemd_units,
    is_daemon_running,
    is_socket_active,
    is_socket_installed,
    is_systemd_available,
    start_daemon,
    stop_daemon,
    uninstall_systemd_units,
)
from testnet import GATE_PORT, LOCALHOST


class TestUnitVersion:
    """Tests for _UNIT_VERSION."""

    def test_unit_version_is_3(self) -> None:
        assert _UNIT_VERSION == 3


class TestSystemdDetection:
    """Tests for systemd availability detection."""

    @unittest.mock.patch("subprocess.run")
    def test_systemd_available(self, mock_run: unittest.mock.Mock) -> None:
        mock_run.return_value = unittest.mock.Mock(returncode=0)
        assert is_systemd_available()

    @unittest.mock.patch("subprocess.run")
    def test_systemd_available_exit_1(self, mock_run: unittest.mock.Mock) -> None:
        mock_run.return_value = unittest.mock.Mock(returncode=1)
        assert is_systemd_available()

    @unittest.mock.patch("subprocess.run", side_effect=FileNotFoundError)
    def test_systemd_not_available(self, _mock: unittest.mock.Mock) -> None:
        assert not is_systemd_available()

    @unittest.mock.patch("subprocess.run")
    def test_systemd_unavailable_exit_2(self, mock_run: unittest.mock.Mock) -> None:
        mock_run.return_value = unittest.mock.Mock(returncode=2)
        assert not is_systemd_available()


class TestSocketInstalled:
    """Tests for socket unit file detection."""

    def test_socket_not_installed(self) -> None:
        with unittest.mock.patch(
            "terok.lib.security.gate_server._systemd_unit_dir",
            return_value=Path("/nonexistent"),
        ):
            assert not is_socket_installed()

    def test_socket_installed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            unit_dir = Path(td)
            (unit_dir / "terok-gate.socket").write_text("[Socket]\n")
            with unittest.mock.patch(
                "terok.lib.security.gate_server._systemd_unit_dir",
                return_value=unit_dir,
            ):
                assert is_socket_installed()


class TestSocketActive:
    """Tests for socket active check."""

    @unittest.mock.patch("subprocess.run")
    def test_active(self, mock_run: unittest.mock.Mock) -> None:
        mock_run.return_value = unittest.mock.Mock(stdout="active\n", returncode=0)
        assert is_socket_active()

    @unittest.mock.patch("subprocess.run")
    def test_inactive(self, mock_run: unittest.mock.Mock) -> None:
        mock_run.return_value = unittest.mock.Mock(stdout="inactive\n", returncode=3)
        assert not is_socket_active()

    @unittest.mock.patch("subprocess.run", side_effect=FileNotFoundError)
    def test_no_systemctl(self, _mock: unittest.mock.Mock) -> None:
        assert not is_socket_active()


class TestInstallUninstall:
    """Tests for systemd unit install/uninstall."""

    @unittest.mock.patch("subprocess.run")
    @unittest.mock.patch("shutil.which", return_value="/usr/local/bin/terok-gate")
    def test_install_writes_files(
        self, _mock_which: unittest.mock.Mock, mock_run: unittest.mock.Mock
    ) -> None:
        mock_run.return_value = unittest.mock.Mock(returncode=0)
        with tempfile.TemporaryDirectory() as td:
            unit_dir = Path(td) / "systemd" / "user"
            with (
                unittest.mock.patch(
                    "terok.lib.security.gate_server._systemd_unit_dir",
                    return_value=unit_dir,
                ),
                unittest.mock.patch(
                    "terok.lib.security.gate_server._get_port", return_value=GATE_PORT
                ),
                unittest.mock.patch(
                    "terok.lib.security.gate_server._get_gate_base_path",
                    return_value=Path("/tmp/gate"),
                ),
                unittest.mock.patch(
                    "terok.lib.security.gate_tokens.state_root",
                    return_value=Path("/tmp/state"),
                ),
            ):
                install_systemd_units()

            assert (unit_dir / "terok-gate.socket").is_file()
            assert (unit_dir / "terok-gate@.service").is_file()
            # Verify socket file contains port
            socket_content = (unit_dir / "terok-gate.socket").read_text()
            assert f"{LOCALHOST}:{GATE_PORT}" in socket_content
            # Verify service file contains absolute path in ExecStart and args
            service_content = (unit_dir / "terok-gate@.service").read_text()
            assert "ExecStart=/usr/local/bin/terok-gate" in service_content
            assert "/tmp/gate" in service_content
            assert "--token-file=" in service_content
            # Verify version stamp is rendered in both files
            version_stamp = f"# terok-gate-version: {_UNIT_VERSION}"
            assert version_stamp in socket_content
            assert version_stamp in service_content

    @unittest.mock.patch("subprocess.run")
    @unittest.mock.patch("shutil.which", return_value=None)
    def test_install_fails_without_binary(
        self, _mock_which: unittest.mock.Mock, _mock_run: unittest.mock.Mock
    ) -> None:
        with pytest.raises(SystemExit) as ctx:
            install_systemd_units()
        assert "terok-gate" in str(ctx.value)

    @unittest.mock.patch("subprocess.run")
    def test_uninstall_removes_files(self, mock_run: unittest.mock.Mock) -> None:
        mock_run.return_value = unittest.mock.Mock(returncode=0)
        with tempfile.TemporaryDirectory() as td:
            unit_dir = Path(td)
            (unit_dir / "terok-gate.socket").write_text("[Socket]\n")
            (unit_dir / "terok-gate@.service").write_text("[Service]\n")

            with unittest.mock.patch(
                "terok.lib.security.gate_server._systemd_unit_dir",
                return_value=unit_dir,
            ):
                uninstall_systemd_units()

            assert not (unit_dir / "terok-gate.socket").exists()
            assert not (unit_dir / "terok-gate@.service").exists()


class TestDaemon:
    """Tests for daemon start/stop."""

    @unittest.mock.patch("subprocess.run")
    def test_start_daemon(self, mock_run: unittest.mock.Mock) -> None:
        mock_run.return_value = unittest.mock.Mock(returncode=0)
        with tempfile.TemporaryDirectory() as td:
            with (
                unittest.mock.patch(
                    "terok.lib.security.gate_server._get_gate_base_path",
                    return_value=Path(td) / "gate",
                ),
                unittest.mock.patch(
                    "terok.lib.security.gate_server._pid_file",
                    return_value=Path(td) / "gate-server.pid",
                ),
                unittest.mock.patch(
                    "terok.lib.security.gate_tokens.state_root",
                    return_value=Path(td),
                ),
            ):
                start_daemon(port=9999)

            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == "terok-gate"
            assert "--port=9999" in cmd
            assert "--detach" in cmd
            # Check --base-path and --token-file are present
            assert any("--base-path=" in arg for arg in cmd)
            assert any("--token-file=" in arg for arg in cmd)

    @unittest.mock.patch(
        "subprocess.run", side_effect=subprocess.CalledProcessError(1, "terok-gate")
    )
    def test_start_daemon_failure(self, _mock: unittest.mock.Mock) -> None:
        with tempfile.TemporaryDirectory() as td:
            with (
                unittest.mock.patch(
                    "terok.lib.security.gate_server._get_gate_base_path",
                    return_value=Path(td) / "gate",
                ),
                unittest.mock.patch(
                    "terok.lib.security.gate_server._pid_file",
                    return_value=Path(td) / "gate-server.pid",
                ),
                unittest.mock.patch(
                    "terok.lib.security.gate_tokens.state_root",
                    return_value=Path(td),
                ),
            ):
                with pytest.raises(subprocess.CalledProcessError):
                    start_daemon(port=9999)

    def test_stop_daemon_no_pidfile(self) -> None:
        with unittest.mock.patch(
            "terok.lib.security.gate_server._pid_file",
            return_value=Path("/nonexistent/pid"),
        ):
            stop_daemon()  # Should not raise

    @unittest.mock.patch("terok.lib.security.gate_server._is_managed_server", return_value=True)
    def test_stop_daemon_with_pidfile(self, _mock_check: unittest.mock.Mock) -> None:
        with tempfile.TemporaryDirectory() as td:
            pidfile = Path(td) / "gate-server.pid"
            pidfile.write_text("99999\n")
            with (
                unittest.mock.patch(
                    "terok.lib.security.gate_server._pid_file",
                    return_value=pidfile,
                ),
                unittest.mock.patch("os.kill") as mock_kill,
            ):
                stop_daemon()
                mock_kill.assert_called_once_with(99999, unittest.mock.ANY)
            assert not pidfile.exists()

    @unittest.mock.patch("terok.lib.security.gate_server._is_managed_server", return_value=False)
    def test_stop_daemon_stale_pid_not_killed(self, _mock_check: unittest.mock.Mock) -> None:
        """Stop removes PID file even if the process is not our daemon."""
        with tempfile.TemporaryDirectory() as td:
            pidfile = Path(td) / "gate-server.pid"
            pidfile.write_text("99999\n")
            with (
                unittest.mock.patch(
                    "terok.lib.security.gate_server._pid_file",
                    return_value=pidfile,
                ),
                unittest.mock.patch("os.kill") as mock_kill,
            ):
                stop_daemon()
                mock_kill.assert_not_called()
            assert not pidfile.exists()


class TestIsDaemonRunning:
    """Tests for is_daemon_running."""

    def test_no_pidfile(self) -> None:
        with unittest.mock.patch(
            "terok.lib.security.gate_server._pid_file",
            return_value=Path("/nonexistent/pid"),
        ):
            assert not is_daemon_running()

    @unittest.mock.patch("terok.lib.security.gate_server._is_managed_server", return_value=True)
    def test_stale_pid(self, _mock_check: unittest.mock.Mock) -> None:
        with tempfile.TemporaryDirectory() as td:
            pidfile = Path(td) / "gate-server.pid"
            pidfile.write_text("99999\n")
            with (
                unittest.mock.patch(
                    "terok.lib.security.gate_server._pid_file",
                    return_value=pidfile,
                ),
                unittest.mock.patch("os.kill", side_effect=ProcessLookupError),
            ):
                assert not is_daemon_running()

    @unittest.mock.patch("terok.lib.security.gate_server._is_managed_server", return_value=True)
    def test_valid_pid(self, _mock_check: unittest.mock.Mock) -> None:
        with tempfile.TemporaryDirectory() as td:
            pidfile = Path(td) / "gate-server.pid"
            pidfile.write_text(f"{os.getpid()}\n")
            with unittest.mock.patch(
                "terok.lib.security.gate_server._pid_file",
                return_value=pidfile,
            ):
                assert is_daemon_running()

    def test_not_our_daemon(self) -> None:
        """PID exists but is not a git daemon — should return False."""
        with tempfile.TemporaryDirectory() as td:
            pidfile = Path(td) / "gate-server.pid"
            pidfile.write_text(f"{os.getpid()}\n")
            with (
                unittest.mock.patch(
                    "terok.lib.security.gate_server._pid_file",
                    return_value=pidfile,
                ),
                unittest.mock.patch(
                    "terok.lib.security.gate_server._is_managed_server",
                    return_value=False,
                ),
            ):
                assert not is_daemon_running()


class TestIsManagedServer:
    """Tests for _is_managed_server."""

    def test_no_proc_entry(self) -> None:
        assert not _is_managed_server(999999999)

    def test_current_process_is_not_gate_server(self) -> None:
        # The current process is python, not terok-gate
        assert not _is_managed_server(os.getpid())

    def _check_cmdline(self, cmdline: bytes, pid_file: Path | None = None) -> bool:
        """Write *cmdline* to a temp file and call ``_is_managed_server``."""
        with tempfile.TemporaryDirectory() as td:
            fake_cmdline = Path(td) / "cmdline"
            fake_cmdline.write_bytes(cmdline)
            patches = [
                unittest.mock.patch(
                    "terok.lib.security.gate_server.Path",
                    return_value=fake_cmdline,
                ),
            ]
            if pid_file is not None:
                patches.append(
                    unittest.mock.patch(
                        "terok.lib.security.gate_server._pid_file",
                        return_value=pid_file,
                    )
                )
            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                return _is_managed_server(12345)

    def test_matches_managed_server(self) -> None:
        """Cmdline with terok-gate and our PID file returns True."""
        pid_file = Path("/run/user/1000/terok/gate-server.pid")
        cmdline = b"terok-gate\x00--base-path=/tmp/gate\x00--pid-file=" + str(pid_file).encode()
        assert self._check_cmdline(cmdline, pid_file)

    def test_rejects_different_pid_file(self) -> None:
        """terok-gate with a different --pid-file is not ours."""
        cmdline = b"terok-gate\x00--base-path=/tmp/gate\x00--pid-file=/other/pid"
        assert not self._check_cmdline(cmdline, Path("/run/user/1000/terok/gate-server.pid"))

    def test_rejects_unrelated_process(self) -> None:
        """Process without our PID file returns False."""
        cmdline = b"python3\x00-m\x00pytest"
        assert not self._check_cmdline(cmdline, Path("/run/user/1000/terok/gate-server.pid"))


class TestGetServerStatus:
    """Tests for get_server_status."""

    @unittest.mock.patch("terok.lib.security.gate_server.is_daemon_running", return_value=False)
    @unittest.mock.patch("terok.lib.security.gate_server.is_socket_installed", return_value=False)
    @unittest.mock.patch("terok.lib.security.gate_server._get_port", return_value=GATE_PORT)
    def test_none(self, *_mocks: unittest.mock.Mock) -> None:
        status = get_server_status()
        assert status == GateServerStatus(mode="none", running=False, port=GATE_PORT)

    @unittest.mock.patch("terok.lib.security.gate_server.is_socket_active", return_value=True)
    @unittest.mock.patch("terok.lib.security.gate_server.is_socket_installed", return_value=True)
    @unittest.mock.patch("terok.lib.security.gate_server._get_port", return_value=GATE_PORT)
    def test_systemd_active(self, *_mocks: unittest.mock.Mock) -> None:
        status = get_server_status()
        assert status == GateServerStatus(mode="systemd", running=True, port=GATE_PORT)

    @unittest.mock.patch("terok.lib.security.gate_server.is_daemon_running", return_value=False)
    @unittest.mock.patch("terok.lib.security.gate_server.is_socket_active", return_value=False)
    @unittest.mock.patch("terok.lib.security.gate_server.is_socket_installed", return_value=True)
    @unittest.mock.patch("terok.lib.security.gate_server._get_port", return_value=GATE_PORT)
    def test_systemd_inactive(self, *_mocks: unittest.mock.Mock) -> None:
        status = get_server_status()
        assert status == GateServerStatus(mode="systemd", running=False, port=GATE_PORT)

    @unittest.mock.patch("terok.lib.security.gate_server.is_daemon_running", return_value=True)
    @unittest.mock.patch("terok.lib.security.gate_server.is_socket_active", return_value=False)
    @unittest.mock.patch("terok.lib.security.gate_server.is_socket_installed", return_value=True)
    @unittest.mock.patch("terok.lib.security.gate_server._get_port", return_value=GATE_PORT)
    def test_daemon_fallback_when_socket_inactive(self, *_mocks: unittest.mock.Mock) -> None:
        """Daemon fallback is detected even when systemd units are installed."""
        status = get_server_status()
        assert status == GateServerStatus(mode="daemon", running=True, port=GATE_PORT)

    @unittest.mock.patch("terok.lib.security.gate_server.is_daemon_running", return_value=True)
    @unittest.mock.patch("terok.lib.security.gate_server.is_socket_installed", return_value=False)
    @unittest.mock.patch("terok.lib.security.gate_server._get_port", return_value=GATE_PORT)
    def test_daemon_running(self, *_mocks: unittest.mock.Mock) -> None:
        status = get_server_status()
        assert status == GateServerStatus(mode="daemon", running=True, port=GATE_PORT)


class TestEnsureServerReachable:
    """Tests for ensure_server_reachable."""

    @unittest.mock.patch(
        "terok.lib.security.gate_server.get_server_status",
        return_value=GateServerStatus(mode="daemon", running=True, port=GATE_PORT),
    )
    def test_passes_when_running(self, _mock: unittest.mock.Mock) -> None:
        ensure_server_reachable()  # Should not raise

    @unittest.mock.patch("terok.lib.security.gate_server.is_systemd_available", return_value=True)
    @unittest.mock.patch(
        "terok.lib.security.gate_server.get_server_status",
        return_value=GateServerStatus(mode="none", running=False, port=GATE_PORT),
    )
    def test_raises_when_not_running_systemd(self, *_mocks: unittest.mock.Mock) -> None:
        with pytest.raises(SystemExit) as ctx:
            ensure_server_reachable()
        assert "gate-server install" in str(ctx.value)

    @unittest.mock.patch("terok.lib.security.gate_server.is_systemd_available", return_value=False)
    @unittest.mock.patch(
        "terok.lib.security.gate_server.get_server_status",
        return_value=GateServerStatus(mode="none", running=False, port=GATE_PORT),
    )
    def test_raises_when_not_running_no_systemd(self, *_mocks: unittest.mock.Mock) -> None:
        with pytest.raises(SystemExit) as ctx:
            ensure_server_reachable()
        assert "gate-server start" in str(ctx.value)

    @unittest.mock.patch(
        "terok.lib.security.gate_server._installed_unit_version",
        return_value=0,
    )
    @unittest.mock.patch(
        "terok.lib.security.gate_server.get_server_status",
        return_value=GateServerStatus(mode="systemd", running=True, port=GATE_PORT),
    )
    def test_raises_when_units_outdated(self, *_mocks: unittest.mock.Mock) -> None:
        with pytest.raises(SystemExit) as ctx:
            ensure_server_reachable()
        assert "outdated" in str(ctx.value)
        assert "gate-server install" in str(ctx.value)

    @unittest.mock.patch(
        "terok.lib.security.gate_server._installed_unit_version",
        return_value=None,
    )
    @unittest.mock.patch(
        "terok.lib.security.gate_server.get_server_status",
        return_value=GateServerStatus(mode="systemd", running=True, port=GATE_PORT),
    )
    def test_raises_when_units_unversioned(self, *_mocks: unittest.mock.Mock) -> None:
        with pytest.raises(SystemExit) as ctx:
            ensure_server_reachable()
        assert "unversioned" in str(ctx.value)

    @unittest.mock.patch(
        "terok.lib.security.gate_server._installed_unit_version",
        return_value=_UNIT_VERSION,
    )
    @unittest.mock.patch(
        "terok.lib.security.gate_server.get_server_status",
        return_value=GateServerStatus(mode="systemd", running=True, port=GATE_PORT),
    )
    def test_passes_when_units_current(self, *_mocks: unittest.mock.Mock) -> None:
        ensure_server_reachable()  # Should not raise


class TestInstalledUnitVersion:
    """Tests for _installed_unit_version."""

    def test_no_file(self) -> None:
        with unittest.mock.patch(
            "terok.lib.security.gate_server._systemd_unit_dir",
            return_value=Path("/nonexistent"),
        ):
            assert _installed_unit_version() is None

    def test_reads_version(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            unit_dir = Path(td)
            (unit_dir / "terok-gate.socket").write_text("# terok-gate-version: 42\n[Socket]\n")
            with unittest.mock.patch(
                "terok.lib.security.gate_server._systemd_unit_dir",
                return_value=unit_dir,
            ):
                assert _installed_unit_version() == 42

    def test_missing_stamp(self) -> None:
        """Unit file without version stamp returns None."""
        with tempfile.TemporaryDirectory() as td:
            unit_dir = Path(td)
            (unit_dir / "terok-gate.socket").write_text(
                f"[Socket]\nListenStream={LOCALHOST}:{GATE_PORT}\n"
            )
            with unittest.mock.patch(
                "terok.lib.security.gate_server._systemd_unit_dir",
                return_value=unit_dir,
            ):
                assert _installed_unit_version() is None


class TestCheckUnitsOutdated:
    """Tests for check_units_outdated."""

    @unittest.mock.patch("terok.lib.security.gate_server.is_socket_installed", return_value=False)
    def test_no_socket_returns_none(self, _mock: unittest.mock.Mock) -> None:
        assert check_units_outdated() is None

    @unittest.mock.patch(
        "terok.lib.security.gate_server._installed_unit_version",
        return_value=_UNIT_VERSION,
    )
    @unittest.mock.patch("terok.lib.security.gate_server.is_socket_installed", return_value=True)
    def test_current_version_returns_none(self, *_mocks: unittest.mock.Mock) -> None:
        assert check_units_outdated() is None

    @unittest.mock.patch("terok.lib.security.gate_server._installed_unit_version", return_value=1)
    @unittest.mock.patch("terok.lib.security.gate_server.is_socket_installed", return_value=True)
    def test_old_version_returns_warning(self, *_mocks: unittest.mock.Mock) -> None:
        result = check_units_outdated()
        assert result is not None
        assert "outdated" in result
        assert "gate-server install" in result

    @unittest.mock.patch(
        "terok.lib.security.gate_server._installed_unit_version", return_value=None
    )
    @unittest.mock.patch("terok.lib.security.gate_server.is_socket_installed", return_value=True)
    def test_unversioned_returns_warning(self, *_mocks: unittest.mock.Mock) -> None:
        result = check_units_outdated()
        assert result is not None
        assert "unversioned" in result
