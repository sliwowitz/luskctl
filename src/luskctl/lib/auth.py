"""Authentication workflows for AI coding agents.

Each public function (codex_auth, claude_auth, mistral_auth, blablador_auth)
sets up credentials for a specific agent inside a temporary L2 CLI container.
The shared helper ``_run_auth_container`` handles the common lifecycle:
check podman, load project, ensure host dir, cleanup old container, run.
"""

import shutil
import subprocess

from .config import get_envs_base_dir
from .fs import _ensure_dir_writable
from .images import project_cli_image
from .podman import _podman_userns_args
from .projects import load_project

# ---------- Shared helper ----------


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


def _run_auth_container(
    project_id: str,
    container_suffix: str,
    host_dir_name: str,
    host_dir_label: str,
    container_mount: str,
    command: list[str],
    banner_lines: list[str],
    extra_run_args: list[str] | None = None,
) -> None:
    """Run an auth container with the common lifecycle.

    Args:
        project_id: The project to authenticate against.
        container_suffix: Suffix for the container name (e.g. "auth-codex").
        host_dir_name: Name of the host directory under envs_base (e.g. "_codex-config").
        host_dir_label: Human label for dir writable check (e.g. "Codex config").
        container_mount: Mount point inside the container (e.g. "/home/dev/.codex").
        command: Command to run inside the container.
        banner_lines: Lines to print before running the container.
        extra_run_args: Additional podman run arguments (e.g. port forwarding).
    """
    _check_podman()

    project = load_project(project_id)

    envs_base = get_envs_base_dir()
    host_dir = envs_base / host_dir_name
    _ensure_dir_writable(host_dir, host_dir_label)

    container_name = f"{project.id}-{container_suffix}"
    _cleanup_existing_container(container_name)

    cmd = [
        "podman",
        "run",
        "--rm",
        "-it",
        "-v",
        f"{host_dir}:{container_mount}:Z",
        "--name",
        container_name,
    ]
    # Insert userns args after the initial flags
    cmd[3:3] = _podman_userns_args()
    if extra_run_args:
        # Insert extra args before the volume mount
        cmd[3:3] = extra_run_args
    cmd.append(project_cli_image(project.id))
    cmd.extend(command)

    for line in banner_lines:
        print(line)
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


# ---------- Codex authentication ----------


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
    _run_auth_container(
        project_id=project_id,
        container_suffix="auth-codex",
        host_dir_name="_codex-config",
        host_dir_label="Codex config",
        container_mount="/home/dev/.codex",
        command=["setup-codex-auth.sh"],
        banner_lines=[
            f"Authenticating Codex for project: {project_id}",
            "",
            "This will set up port forwarding (using socat) and open a browser for authentication.",
            "After completing authentication, press Ctrl+C to stop the container.",
            "",
        ],
        extra_run_args=["-p", "127.0.0.1:1455:1455"],
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
    _run_auth_container(
        project_id=project_id,
        container_suffix="auth-claude",
        host_dir_name="_claude-config",
        host_dir_label="Claude config",
        container_mount="/home/dev/.claude",
        command=[
            "bash",
            "-c",
            "echo 'Enter your Claude API key (get one at https://console.anthropic.com/settings/keys):' && "
            "read -r -p 'ANTHROPIC_API_KEY=' api_key && "
            "mkdir -p ~/.claude && "
            'echo \'{"api_key": "$api_key"}\' > ~/.claude/config.json && '
            "echo && echo 'API key saved to ~/.claude/config.json' && "
            "echo 'You can now use claude in task containers.'",
        ],
        banner_lines=[
            f"Authenticating Claude for project: {project_id}",
            "",
            "You will be prompted to enter your Claude API key.",
            "Get your API key at: https://console.anthropic.com/settings/keys",
            "",
        ],
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
    _run_auth_container(
        project_id=project_id,
        container_suffix="auth-mistral",
        host_dir_name="_vibe-config",
        host_dir_label="Vibe config",
        container_mount="/home/dev/.vibe",
        command=[
            "bash",
            "-c",
            "echo 'Enter your Mistral API key (get one at https://console.mistral.ai/api-keys):' && "
            "read -r -p 'MISTRAL_API_KEY=' api_key && "
            "mkdir -p ~/.vibe && "
            'echo "MISTRAL_API_KEY=$api_key" > ~/.vibe/.env && '
            "echo && echo 'API key saved to ~/.vibe/.env' && "
            "echo 'You can now use vibe in task containers.'",
        ],
        banner_lines=[
            f"Authenticating Mistral Vibe for project: {project_id}",
            "",
            "You will be prompted to enter your Mistral API key.",
            "Get your API key at: https://console.mistral.ai/api-keys",
            "",
        ],
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
    _run_auth_container(
        project_id=project_id,
        container_suffix="auth-blablador",
        host_dir_name="_blablador-config",
        host_dir_label="Blablador config",
        container_mount="/home/dev/.blablador",
        command=[
            "bash",
            "-c",
            "echo 'Enter your Blablador API key (get one at https://codebase.helmholtz.cloud/-/user_settings/personal_access_tokens):' && "
            "read -r -p 'BLABLADOR_API_KEY=' api_key && "
            "mkdir -p ~/.blablador && "
            'echo "{\\"api_key\\": \\"$api_key\\"}" > ~/.blablador/config.json && '
            "echo && echo 'API key saved to ~/.blablador/config.json' && "
            "echo 'You can now use blablador in task containers.'",
        ],
        banner_lines=[
            f"Authenticating Blablador for project: {project_id}",
            "",
            "You will be prompted to enter your Blablador API key.",
            "Get your API key at: https://codebase.helmholtz.cloud/-/user_settings/personal_access_tokens",
            "",
        ],
    )
