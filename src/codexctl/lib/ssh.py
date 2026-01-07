from __future__ import annotations

import getpass
import os
import socket
import subprocess
from importlib import resources
from pathlib import Path
from typing import Optional

from .config import get_envs_base_dir
from .fs import _ensure_dir_writable
from .projects import _effective_ssh_key_name, load_project
from .template_utils import render_template


# ---------- SSH shared dir initialization ----------
def init_project_ssh(
    project_id: str,
    key_type: str = "ed25519",
    key_name: Optional[str] = None,
    force: bool = False,
) -> dict:
    """Initialize the shared SSH directory for a project and generate a keypair.

    This prepares the host directory that containers mount read-write at /home/dev/.ssh
    and creates an SSH keypair plus a minimal config file if missing.

    Location resolution:
      - If project.yml defines ssh.host_dir, use that path.
      - Otherwise: <envs_base>/_ssh-config-<project_id>

    Key name:
      - Defaults to id_<type>_<project_id> (e.g. id_ed25519_proj)

    Returns a dict with keys: dir, private_key, public_key, config_path, key_name.
    """
    if key_type not in ("ed25519", "rsa"):
        raise SystemExit("Unsupported --key-type. Use 'ed25519' or 'rsa'.")

    project = load_project(project_id)

    target_dir = project.ssh_host_dir or (get_envs_base_dir() / f"_ssh-config-{project.id}")
    target_dir = Path(target_dir).expanduser().resolve()
    _ensure_dir_writable(target_dir, "SSH host dir")

    # If caller did not supply an explicit key_name, derive it from project
    # configuration using the shared helper so ssh-init, containers and git
    # helpers all agree on the filename.
    if not key_name:
        key_name = _effective_ssh_key_name(project, key_type=key_type)

    priv_path = target_dir / key_name
    pub_path = target_dir / f"{key_name}.pub"
    cfg_path = target_dir / "config"

    # Generate keypair if needed (or forced)
    need_generate = force or (not priv_path.exists() or not pub_path.exists())
    if need_generate:
        # Remove existing when forced to avoid ssh-keygen prompt
        if force:
            try:
                if priv_path.exists():
                    priv_path.unlink()
                if pub_path.exists():
                    pub_path.unlink()
            except Exception:
                # Best-effort cleanup before regenerating keys.
                pass

        cmd = ["ssh-keygen", "-t", key_type, "-f", str(priv_path), "-N", "", "-C", f"codexctl {project.id} {getpass.getuser()}@{socket.gethostname()}"]
        try:
            subprocess.run(cmd, check=True)
        except FileNotFoundError:
            raise SystemExit("ssh-keygen not found. Please install OpenSSH client tools.")
        except subprocess.CalledProcessError as e:
            raise SystemExit(f"ssh-keygen failed: {e}")

        # Best-effort permissions
        try:
            os.chmod(priv_path, 0o600)
            os.chmod(pub_path, 0o644)
        except Exception:
            # Permission adjustments are best-effort.
            pass

    # Ensure config exists and references the key. Render from user or packaged template.
    if (force and cfg_path.exists()) or (not cfg_path.exists()):
        # If force, overwrite; otherwise create if missing
        # Prefer project-provided template; else use packaged default.
        user_template_path: Optional[Path] = None
        if getattr(project, "ssh_config_template", None):
            tp: Path = project.ssh_config_template  # type: ignore[assignment]
            if tp.is_file():
                user_template_path = tp
        # Packaged template (importlib.resources Traversable)
        packaged_template = None
        try:
            packaged_template = resources.files("codexctl") / "resources" / "templates" / "ssh_config.template"
        except Exception:
            packaged_template = None

        config_text: Optional[str] = None
        variables = {
            "KEY_NAME": key_name,
        }
        # Prefer user template if provided
        if user_template_path is not None:
            try:
                config_text = render_template(user_template_path, variables)
            except Exception:
                config_text = None
        # Otherwise use packaged template (works from wheels/zip)
        if not config_text and packaged_template is not None:
            try:
                raw = packaged_template.read_text()
                for k, v in variables.items():
                    raw = raw.replace(f"{{{{{k}}}}}", str(v))
                config_text = raw
            except Exception:
                config_text = None

        if not config_text:
            raise SystemExit(
                "Failed to render SSH config: no valid template. "
                "Ensure a project ssh.config_template is set or the packaged template exists."
            )

        try:
            cfg_path.write_text(config_text)
        except Exception as e:
            raise SystemExit(f"Failed to write SSH config at {cfg_path}: {e}")

    # Best-effort permissions for container dev user access.
    try:
        os.chmod(target_dir, 0o700)
        if priv_path.exists():
            os.chmod(priv_path, 0o600)
        if pub_path.exists():
            os.chmod(pub_path, 0o644)
        if cfg_path.exists():
            os.chmod(cfg_path, 0o644)
    except Exception:
        # Permission adjustments are best-effort.
        pass

    print("SSH directory initialized:")
    print(f"  dir:         {target_dir}")
    print(f"  private key: {priv_path}")
    print(f"  public key:  {pub_path}")
    print(f"  config:      {cfg_path}")

    # Also echo the actual public key contents for easy copy-paste.
    # Best-effort: if reading fails, continue without raising.
    try:
        if pub_path.exists():
            pub_key_text = pub_path.read_text(encoding="utf-8", errors="ignore").strip()
            if pub_key_text:
                print("Public key:")
                print(f"  {pub_key_text}")
    except Exception:
        # Reading the public key is best-effort.
        pass
    # When ssh.key_name is omitted in project.yml, we still derive a stable
    # default filename (id_<algo>_<project_id>) via _effective_ssh_key_name.
    # Containers receive only this bare filename via SSH_KEY_NAME and mount
    # the host ssh_host_dir at /home/dev/.ssh, so path handling remains
    # host-side while the filename is consistent everywhere.
    if not project.ssh_key_name:
        print("Note: project.yml does not define ssh.key_name; using a derived default key filename.")
        print(f"      To pin the SSH key filename explicitly, add to {project.root/'project.yml'}:\n        ssh:\n          key_name: {key_name}")

    return {
        "dir": str(target_dir),
        "private_key": str(priv_path),
        "public_key": str(pub_path),
        "config_path": str(cfg_path),
        "key_name": key_name,
    }
