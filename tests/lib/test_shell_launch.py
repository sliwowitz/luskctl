import subprocess
import unittest
import unittest.mock

from luskctl.lib.shell_launch import (
    detect_terminal_emulator,
    is_inside_tmux,
    launch_login,
    spawn_terminal_with_command,
    tmux_new_window,
)


class TmuxDetectionTests(unittest.TestCase):
    """Tests for tmux environment detection."""

    def test_is_inside_tmux_true(self) -> None:
        with unittest.mock.patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,12345,0"}):
            self.assertTrue(is_inside_tmux())

    def test_is_inside_tmux_false(self) -> None:
        with unittest.mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(is_inside_tmux())


class TmuxNewWindowTests(unittest.TestCase):
    """Tests for tmux_new_window."""

    def test_success(self) -> None:
        with unittest.mock.patch("luskctl.lib.shell_launch.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            result = tmux_new_window(["podman", "exec", "-it", "c1", "bash"], title="login:c1")
            self.assertTrue(result)
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            self.assertEqual(call_args[:2], ["tmux", "new-window"])
            self.assertIn("-n", call_args)
            self.assertIn("login:c1", call_args)

    def test_failure(self) -> None:
        with unittest.mock.patch("luskctl.lib.shell_launch.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "tmux")
            result = tmux_new_window(["podman", "exec", "-it", "c1", "bash"])
            self.assertFalse(result)

    def test_tmux_not_found(self) -> None:
        with unittest.mock.patch("luskctl.lib.shell_launch.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("tmux")
            result = tmux_new_window(["echo", "hello"])
            self.assertFalse(result)


class DetectTerminalTests(unittest.TestCase):
    """Tests for detect_terminal_emulator."""

    def test_gnome_terminal(self) -> None:
        def which_side_effect(name: str):
            return "/usr/bin/gnome-terminal" if name == "gnome-terminal" else None

        with unittest.mock.patch(
            "luskctl.lib.shell_launch.shutil.which", side_effect=which_side_effect
        ):
            self.assertEqual(detect_terminal_emulator(), "gnome-terminal")

    def test_konsole_only(self) -> None:
        def which_side_effect(name: str):
            return "/usr/bin/konsole" if name == "konsole" else None

        with unittest.mock.patch(
            "luskctl.lib.shell_launch.shutil.which", side_effect=which_side_effect
        ):
            self.assertEqual(detect_terminal_emulator(), "konsole")

    def test_none_available(self) -> None:
        with unittest.mock.patch("luskctl.lib.shell_launch.shutil.which", return_value=None):
            self.assertIsNone(detect_terminal_emulator())


class SpawnTerminalTests(unittest.TestCase):
    """Tests for spawn_terminal_with_command."""

    def test_gnome_terminal(self) -> None:
        def which_side_effect(name: str):
            return "/usr/bin/gnome-terminal" if name == "gnome-terminal" else None

        with (
            unittest.mock.patch(
                "luskctl.lib.shell_launch.shutil.which", side_effect=which_side_effect
            ),
            unittest.mock.patch("luskctl.lib.shell_launch.subprocess.Popen") as mock_popen,
        ):
            result = spawn_terminal_with_command(["podman", "exec", "-it", "c1", "bash"])
            self.assertTrue(result)
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args[0][0]
            self.assertEqual(call_args[0], "gnome-terminal")
            self.assertIn("--", call_args)

    def test_konsole(self) -> None:
        def which_side_effect(name: str):
            return "/usr/bin/konsole" if name == "konsole" else None

        with (
            unittest.mock.patch(
                "luskctl.lib.shell_launch.shutil.which", side_effect=which_side_effect
            ),
            unittest.mock.patch("luskctl.lib.shell_launch.subprocess.Popen") as mock_popen,
        ):
            result = spawn_terminal_with_command(["podman", "exec", "-it", "c1", "bash"])
            self.assertTrue(result)
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args[0][0]
            self.assertEqual(call_args[0], "konsole")
            self.assertIn("-e", call_args)

    def test_no_terminal(self) -> None:
        with unittest.mock.patch("luskctl.lib.shell_launch.shutil.which", return_value=None):
            result = spawn_terminal_with_command(["echo", "hello"])
            self.assertFalse(result)


class LaunchLoginTests(unittest.TestCase):
    """Tests for the launch_login orchestrator."""

    def test_prefers_tmux(self) -> None:
        """When inside tmux and terminal is available, tmux is preferred."""
        with (
            unittest.mock.patch("luskctl.lib.shell_launch.is_inside_tmux", return_value=True),
            unittest.mock.patch("luskctl.lib.shell_launch.tmux_new_window", return_value=True),
            unittest.mock.patch(
                "luskctl.lib.shell_launch.detect_terminal_emulator",
                return_value="gnome-terminal",
            ),
        ):
            method, port = launch_login(["podman", "exec", "-it", "c1", "bash"])
            self.assertEqual(method, "tmux")
            self.assertIsNone(port)

    def test_falls_back_to_terminal(self) -> None:
        """When not inside tmux but terminal is available, use terminal."""
        with (
            unittest.mock.patch("luskctl.lib.shell_launch.is_inside_tmux", return_value=False),
            unittest.mock.patch("luskctl.lib.shell_launch.is_web_mode", return_value=False),
            unittest.mock.patch(
                "luskctl.lib.shell_launch.spawn_terminal_with_command", return_value=True
            ),
        ):
            method, port = launch_login(["podman", "exec", "-it", "c1", "bash"])
            self.assertEqual(method, "terminal")
            self.assertIsNone(port)

    def test_returns_none_when_nothing_available(self) -> None:
        """When no method is available, return ('none', None)."""
        with (
            unittest.mock.patch("luskctl.lib.shell_launch.is_inside_tmux", return_value=False),
            unittest.mock.patch("luskctl.lib.shell_launch.is_web_mode", return_value=False),
            unittest.mock.patch(
                "luskctl.lib.shell_launch.spawn_terminal_with_command", return_value=False
            ),
        ):
            method, port = launch_login(["podman", "exec", "-it", "c1", "bash"])
            self.assertEqual(method, "none")
            self.assertIsNone(port)
