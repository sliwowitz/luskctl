from __future__ import annotations

import shutil
import subprocess

from .config import get_envs_base_dir
from .fs import _ensure_dir_writable
from .podman import _podman_userns_args
from .projects import load_project


# ---------- Codex authentication ----------

def codex_auth(project_id: str) -> None:
    """Run codex login inside the L2 container to authenticate the Codex CLI.

    This command:
    - Spins up a temporary L2 container for the project (L2 has the codex CLI)
    - Mounts the shared codex config directory (/home/dev/.codex)
    - Forwards port 1455 from the container to localhost for OAuth callback
    - Runs `codex login` interactively
    - The authentication persists in the shared .codex folder

    The user can press Ctrl+C to stop the container after authentication is complete.
    """
    # Verify podman is available before proceeding
    if shutil.which("podman") is None:
        raise SystemExit("podman not found; please install podman")

    project = load_project(project_id)

    # Shared env mounts - we only need the codex config directory
    envs_base = get_envs_base_dir()
    codex_host_dir = envs_base / "_codex-config"
    _ensure_dir_writable(codex_host_dir, "Codex config")

    container_name = f"{project.id}-auth"

    # Check if a container with the same name is already running
    result = subprocess.run(
        ["podman", "container", "exists", container_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode == 0:
        print(f"Removing existing auth container: {container_name}")
        subprocess.run(
            ["podman", "rm", "-f", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # Build the podman run command
    # - Interactive with TTY for codex login
    # - Port 1455 is the default port used by `codex login` for OAuth callback
    # - Mount codex config dir for persistent auth
    # - Use L2 image (which has the codex CLI installed)
    cmd = [
        "podman", "run",
        "--rm",
        "-it",
        "-p", "127.0.0.1:1455:1455",
        "-v", f"{codex_host_dir}:/home/dev/.codex:Z",
        "--name", container_name,
        f"{project.id}:l2",
        "codex", "login",
    ]
    cmd[3:3] = _podman_userns_args()

    print("Authenticating Codex for project:", project.id)
    print()
    print("This will open a browser for authentication.")
    print("After completing authentication, press Ctrl+C to stop the container.")
    print()
    print("$", " ".join(map(str, cmd)))
    print()

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        # Exit code 130 is typically Ctrl+C (SIGINT), which is expected
        if e.returncode == 130:
            print("\nAuthentication container stopped.")
        else:
            raise SystemExit(f"Auth failed: {e}")
    except KeyboardInterrupt:
        print("\nAuthentication interrupted.")
        # Best-effort cleanup
        subprocess.run(
            ["podman", "rm", "-f", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
