import shutil
import subprocess

from .config import get_envs_base_dir
from .fs import _ensure_dir_writable
from .images import project_cli_image
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
    """Run codex login inside the L2 CLI container to authenticate the Codex CLI.

    This command:
    - Spins up a temporary L2 CLI container for the project (L2 has the codex CLI)
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

    # Build the podman run command
    # - Interactive with TTY for codex login
    # - Port 1455 is the default port used by `codex login` for OAuth callback
    # - Mount codex config dir for persistent auth
    # - Use L2 CLI image (which has the codex CLI installed)
    # - Run setup-codex-auth.sh script which handles port forwarding and codex login
    cmd = [
        "podman",
        "run",
        "--rm",
        "-it",
        "-p",
        "127.0.0.1:1455:1455",
        "-v",
        f"{codex_host_dir}:/home/dev/.codex:Z",
        "--name",
        container_name,
        project_cli_image(project.id),
        "setup-codex-auth.sh",
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
    """Set up Claude API key for CLI inside the L2 CLI container.

    This command:
    - Spins up a temporary L2 CLI container for the project (L2 has the claude CLI)
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
    # - Use L2 CLI image (which has claude CLI installed)
    cmd = [
        "podman",
        "run",
        "--rm",
        "-it",
        "-v",
        f"{claude_host_dir}:/home/dev/.claude:Z",
        "--name",
        container_name,
        project_cli_image(project.id),
        "bash",
        "-c",
        "echo 'Enter your Claude API key (get one at https://console.anthropic.com/settings/keys):' && "
        "read -r -p 'ANTHROPIC_API_KEY=' api_key && "
        "mkdir -p ~/.claude && "
        'echo \'{"api_key": "$api_key"}\' > ~/.claude/config.json && '
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
    """Set up Mistral API key for Vibe CLI inside the L2 CLI container.

    This command:
    - Spins up a temporary L2 CLI container for the project (L2 has mistral-vibe)
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
    # - Use L2 CLI image (which has mistral-vibe installed)
    cmd = [
        "podman",
        "run",
        "--rm",
        "-it",
        "-v",
        f"{vibe_host_dir}:/home/dev/.vibe:Z",
        "--name",
        container_name,
        project_cli_image(project.id),
        "bash",
        "-c",
        "echo 'Enter your Mistral API key (get one at https://console.mistral.ai/api-keys):' && "
        "read -r -p 'MISTRAL_API_KEY=' api_key && "
        "mkdir -p ~/.vibe && "
        'echo "MISTRAL_API_KEY=$api_key" > ~/.vibe/.env && '
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


# ---------- Blablador authentication ----------


def blablador_auth(project_id: str) -> None:
    """Set up Blablador API key for OpenCode inside the L2 CLI container.

    This command:
    - Spins up a temporary L2 CLI container for the project (L2 has OpenCode + blablador wrapper)
    - Mounts the shared blablador config directory (/home/dev/.blablador)
    - Runs an interactive shell where the user can enter their Blablador API key
    - The API key persists in the shared .blablador folder

    Blablador stores the API key in ~/.blablador/config.json as {"api_key": "<key>"}.
    """
    _check_podman()

    project = load_project(project_id)

    # Shared env mounts - we only need the blablador config directory
    envs_base = get_envs_base_dir()
    blablador_host_dir = envs_base / "_blablador-config"
    _ensure_dir_writable(blablador_host_dir, "Blablador config")

    container_name = f"{project.id}-auth-blablador"
    _cleanup_existing_container(container_name)

    # Build the podman run command
    # - Interactive with TTY for API key entry
    # - Mount blablador config dir for persistent auth
    # - Use L2 CLI image (which has OpenCode + blablador wrapper installed)
    cmd = [
        "podman",
        "run",
        "--rm",
        "-it",
        "-v",
        f"{blablador_host_dir}:/home/dev/.blablador:Z",
        "--name",
        container_name,
        project_cli_image(project.id),
        "bash",
        "-c",
        "echo 'Enter your Blablador API key (get one at https://codebase.helmholtz.cloud/-/user_settings/personal_access_tokens):' && "
        "read -r -p 'BLABLADOR_API_KEY=' api_key && "
        "mkdir -p ~/.blablador && "
        'echo "{\\"api_key\\": \\"$api_key\\"}" > ~/.blablador/config.json && '
        "echo && echo 'API key saved to ~/.blablador/config.json' && "
        "echo 'You can now use blablador in task containers.'",
    ]
    cmd[3:3] = _podman_userns_args()

    print("Authenticating Blablador for project:", project.id)
    print()
    print("You will be prompted to enter your Blablador API key.")
    print(
        "Get your API key at: https://codebase.helmholtz.cloud/-/user_settings/personal_access_tokens"
    )
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
