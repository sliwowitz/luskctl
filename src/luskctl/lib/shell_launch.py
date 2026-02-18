"""Helpers for launching interactive login shells from the TUI.

Provides tmux detection, desktop terminal detection, web-mode ttyd spawning,
and an orchestrator that picks the best available method.
"""

import os
import shlex
import shutil
import socket
import subprocess


def is_inside_tmux() -> bool:
    """Return True if the current process is running inside a tmux session."""
    return bool(os.environ.get("TMUX"))


def tmux_new_window(command: list[str], title: str | None = None) -> bool:
    """Open a new tmux window running the given command.

    Returns True if the tmux command succeeded, False otherwise.
    The caller must verify that we are inside tmux before calling this.
    """
    shell_cmd = " ".join(shlex.quote(c) for c in command)
    tmux_cmd: list[str] = ["tmux", "new-window"]
    if title:
        tmux_cmd += ["-n", title]
    tmux_cmd.append(shell_cmd)
    try:
        subprocess.run(tmux_cmd, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def detect_terminal_emulator() -> str | None:
    """Detect an available graphical terminal emulator.

    Returns the name of the first available terminal emulator found,
    or None if no supported terminal is available.  Currently supports
    gnome-terminal (GNOME) and konsole (KDE).
    """
    candidates = ["gnome-terminal", "konsole"]
    for name in candidates:
        if shutil.which(name):
            return name
    return None


def spawn_terminal_with_command(command: list[str]) -> bool:
    """Spawn a new terminal window running the given command.

    Returns True if the terminal was spawned, False if no terminal
    emulator was found or if the spawn failed.
    """
    terminal = detect_terminal_emulator()
    if not terminal:
        return False

    shell_cmd = " ".join(shlex.quote(c) for c in command)

    try:
        if terminal == "gnome-terminal":
            subprocess.Popen(
                ["gnome-terminal", "--", "bash", "-c", shell_cmd + "; exec bash"],
                start_new_session=True,
            )
        elif terminal == "konsole":
            subprocess.Popen(
                ["konsole", "-e", "bash", "-c", shell_cmd + "; exec bash"],
                start_new_session=True,
            )
        else:
            return False
        return True
    except (FileNotFoundError, OSError):
        return False


def is_web_mode() -> bool:
    """Detect if the app is running under textual-serve (web mode).

    When served via ``textual serve``, the TERM_PROGRAM environment
    variable is typically absent and the textual driver changes.  We
    check for the presence of an env var set by textual-serve.
    """
    # textual-serve sets TEXTUAL_DRIVER when running in web mode
    driver = os.environ.get("TEXTUAL_DRIVER", "")
    return "web" in driver.lower()


def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def spawn_ttyd(command: list[str], port: int = 0) -> int | None:
    """Start ttyd serving the given command on a local port.

    Binds to the loopback interface only (``-i lo``) so the terminal is not
    exposed beyond localhost.  Returns the port number on success, or None
    if ttyd is not installed.  If port is 0, a free port is selected
    automatically.
    """
    if not shutil.which("ttyd"):
        return None

    if port == 0:
        port = _find_free_port()

    ttyd_cmd = ["ttyd", "-W", "-o", "-i", "lo", "-p", str(port)] + command
    try:
        subprocess.Popen(ttyd_cmd, start_new_session=True)
        return port
    except (FileNotFoundError, OSError):
        return None


def launch_login(
    command: list[str],
    title: str | None = None,
) -> tuple[str, int | None]:
    """Launch a login session using the best available method.

    Returns a tuple of (method, port):
    - ("tmux", None): opened in a new tmux window
    - ("terminal", None): opened in a new desktop terminal window
    - ("web", port): started ttyd on the given port (caller should open_url)
    - ("none", None): no external method available; caller should suspend
    """
    if is_inside_tmux():
        if tmux_new_window(command, title=title):
            return ("tmux", None)

    if not is_web_mode():
        if spawn_terminal_with_command(command):
            return ("terminal", None)

    if is_web_mode():
        port = spawn_ttyd(command)
        if port is not None:
            return ("web", port)

    return ("none", None)
