from __future__ import annotations

import shutil
import subprocess

from .config import get_envs_base_dir
from .fs import _ensure_dir_writable
from .podman import _podman_userns_args
from .projects import load_project


# ---------- Codex authentication ----------

def _check_podman() -> None:
    """Verify podman is available."""
    if shutil.which("podman") is None:
        raise SystemExit("podman not found; please install podman")


def _cleanup_existing_container(container_name: str) -> None:
    """Remove an existing container if it exists."""
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


def codex_auth(project_id: str) -> None:
    """Run codex login inside the L2 container to authenticate the Codex CLI.

    This command:
    - Spins up a temporary L2 container for the project (L2 has the codex CLI)
    - Mounts the shared codex config directory (/home/dev/.codex)
    - Forwards port 1455 from the container to localhost for OAuth callback
    - Sets up socat port forwarding for port 1455 (required for rootless podman)
    - Runs `codex login` interactively
    - The authentication persists in the shared .codex folder

    The user can press Ctrl+C to stop the container after authentication is complete.
    """
    _check_podman()

    project = load_project(project_id)

    # Shared env mounts - we only need the codex config directory
    envs_base = get_envs_base_dir()
    codex_host_dir = envs_base / "_codex-config"
    _ensure_dir_writable(codex_host_dir, "Codex config")

    container_name = f"{project.id}-auth-codex"
    _cleanup_existing_container(container_name)

    # Setup script for port forwarding (required for codex login in rootless podman)
    # This configures port 1455 forwarding for OAuth callbacks using socat.
    # In rootless podman, we need to forward from the container IP to localhost.
    setup_and_run_script = (
        "set -e && "
        "echo '>> Setting up port forwarding for codex auth (port 1455)' && "
        "echo '>> Installing required packages...' && "
        "sudo apt-get update -qq && "
        "sudo apt-get install -y socat iproute2 && "
        "echo '>> Getting container IP address...' && "
        "CIP=$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -n1) && "
        "echo \">> Container IP: $CIP\" && "
        "echo '>> Starting socat port forwarder in background...' && "
        "socat -v TCP-LISTEN:1455,bind=$CIP,fork,reuseaddr TCP:127.0.0.1:1455 & "
        "SOCAT_PID=$! && "
        "echo \">> socat running (PID: $SOCAT_PID)\" && "
        "echo '>> Starting codex login...' && "
        "codex login; "
        "EXIT_CODE=$? && "
        "echo '>> Stopping socat...' && "
        "kill $SOCAT_PID 2>/dev/null || true && "
        "exit $EXIT_CODE"
    )

    # Build the podman run command
    # - Interactive with TTY for codex login
    # - Port 1455 is the default port used by `codex login` for OAuth callback
    # - Mount codex config dir for persistent auth
    # - Use L2 image (which has the codex CLI installed)
    # - Run setup script followed by codex login
    cmd = [
        "podman", "run",
        "--rm",
        "-it",
        "-p", "127.0.0.1:1455:1455",
        "-v", f"{codex_host_dir}:/home/dev/.codex:Z",
        "--name", container_name,
        f"{project.id}:l2",
        "bash", "-c", setup_and_run_script,
    ]
    cmd[3:3] = _podman_userns_args()

    print("Authenticating Codex for project:", project.id)
    print()
    print("This will set up port forwarding (using socat) and open a browser for authentication.")
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


# ---------- Claude authentication ----------


def claude_auth(project_id: str) -> None:
    """Set up Claude API key for CLI inside the L2 container.

    This command:
    - Spins up a temporary L2 container for the project (L2 has the claude CLI)
    - Mounts the shared claude config directory (/home/dev/.claude)
    - Runs an interactive shell where the user can enter their Claude API key
    - The API key persists in the shared .claude folder

    Claude stores the API key in ~/.claude/config.json or similar configuration.
    """
    _check_podman()

    project = load_project(project_id)

    # Shared env mounts - we only need the claude config directory
    envs_base = get_envs_base_dir()
    claude_host_dir = envs_base / "_claude-config"
    _ensure_dir_writable(claude_host_dir, "Claude config")

    container_name = f"{project.id}-auth-claude"
    _cleanup_existing_container(container_name)

    # Build the podman run command
    # - Interactive with TTY for API key entry
    # - Mount claude config dir for persistent auth
    # - Use L2 image (which has claude CLI installed)
    cmd = [
        "podman", "run",
        "--rm",
        "-it",
        "-v", f"{claude_host_dir}:/home/dev/.claude:Z",
        "--name", container_name,
        f"{project.id}:l2",
        "bash", "-c",
        "echo 'Enter your Claude API key (get one at https://console.anthropic.com/settings/keys):' && "
        "read -r -p 'ANTHROPIC_API_KEY=' api_key && "
        "mkdir -p ~/.claude && "
        "echo '{\"api_key\": \"$api_key\"}' > ~/.claude/config.json && "
        "echo && echo 'API key saved to ~/.claude/config.json' && "
        "echo 'You can now use claude in task containers.'",
    ]
    cmd[3:3] = _podman_userns_args()

    print("Authenticating Claude for project:", project.id)
    print()
    print("You will be prompted to enter your Claude API key.")
    print("Get your API key at: https://console.anthropic.com/settings/keys")
    print()
    print("$", " ".join(map(str, cmd)))
    print()

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        if e.returncode == 130:
            print("\nAuthentication container stopped.")
        else:
            raise SystemExit(f"Auth failed: {e}")
    except KeyboardInterrupt:
        print("\nAuthentication interrupted.")
        subprocess.run(
            ["podman", "rm", "-f", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


# ---------- Mistral Vibe authentication ----------

def mistral_auth(project_id: str) -> None:
    """Set up Mistral API key for Vibe CLI inside the L2 container.

    This command:
    - Spins up a temporary L2 container for the project (L2 has mistral-vibe)
    - Mounts the shared vibe config directory (/home/dev/.vibe)
    - Runs an interactive shell where the user can run `vibe` to trigger
      the API key prompt, or manually create ~/.vibe/.env
    - The API key persists in the shared .vibe folder

    Mistral Vibe stores the API key in ~/.vibe/.env as MISTRAL_API_KEY=<key>.
    """
    _check_podman()

    project = load_project(project_id)

    # Shared env mounts - we only need the vibe config directory
    envs_base = get_envs_base_dir()
    vibe_host_dir = envs_base / "_vibe-config"
    _ensure_dir_writable(vibe_host_dir, "Vibe config")

    container_name = f"{project.id}-auth-mistral"
    _cleanup_existing_container(container_name)

    # Build the podman run command
    # - Interactive with TTY for API key entry
    # - Mount vibe config dir for persistent auth
    # - Use L2 image (which has mistral-vibe installed)
    cmd = [
        "podman", "run",
        "--rm",
        "-it",
        "-v", f"{vibe_host_dir}:/home/dev/.vibe:Z",
        "--name", container_name,
        f"{project.id}:l2",
        "bash", "-c",
        "echo 'Enter your Mistral API key (get one at https://console.mistral.ai/api-keys):' && "
        "read -r -p 'MISTRAL_API_KEY=' api_key && "
        "mkdir -p ~/.vibe && "
        "echo \"MISTRAL_API_KEY=$api_key\" > ~/.vibe/.env && "
        "echo && echo 'API key saved to ~/.vibe/.env' && "
        "echo 'You can now use vibe in task containers.'",
    ]
    cmd[3:3] = _podman_userns_args()

    print("Authenticating Mistral Vibe for project:", project.id)
    print()
    print("You will be prompted to enter your Mistral API key.")
    print("Get your API key at: https://console.mistral.ai/api-keys")
    print()
    print("$", " ".join(map(str, cmd)))
    print()

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        if e.returncode == 130:
            print("\nAuthentication container stopped.")
        else:
            raise SystemExit(f"Auth failed: {e}")
    except KeyboardInterrupt:
        print("\nAuthentication interrupted.")
        subprocess.run(
            ["podman", "rm", "-f", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
