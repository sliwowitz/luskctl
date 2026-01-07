#!/usr/bin/env python3
# Moved from bin/codexctl_lib.py into package module codexctl.lib

from __future__ import annotations

# Keep the file content identical to the previous implementation for minimal diff.
# The original bin/codexctl_lib.py is retained for developers running from the
# repo, but packaging and entry points now import this module.

import os
import sys
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml  # pip install pyyaml
from importlib import resources
import shutil
import getpass
import time
import threading
import select

from .paths import config_root as _config_root_base, state_root as _state_root_base


# ---------- Prefix & roots ----------

def get_prefix() -> Path:
    """
    Minimal prefix helper used primarily for pip/venv installs.

    Order:
    - If CODEXCTL_PREFIX is set, use it.
    - Otherwise, use sys.prefix.

    Note: Do not use this for config/data discovery – see the dedicated
    helpers below which follow common Linux/XDG conventions.
    """
    env = os.environ.get("CODEXCTL_PREFIX")
    if env:
        return Path(env).expanduser().resolve()
    return Path(sys.prefix).resolve()


def config_root() -> Path:
    """
    System projects directory. Uses FHS/XDG via codexctl.paths.

    Behavior:
    - If the base config directory contains a 'projects' subdirectory, use it.
    - Otherwise, treat the base config directory itself as the projects root.

    This makes development convenient when CODEXCTL_CONFIG_DIR points directly
    to a folder that already contains per-project subdirectories (like ./examples).
    """
    base = _config_root_base().resolve()
    proj_dir = base / "projects"
    return proj_dir if proj_dir.is_dir() else base


def global_config_search_paths() -> list[Path]:
    """Return the ordered list of paths that will be checked for global config.

    Behavior matches global_config_path():
    - If CODEXCTL_CONFIG_FILE is set, only that single path is considered.
    - Otherwise, check in order:
        1) ${XDG_CONFIG_HOME:-~/.config}/codexctl/config.yml
        2) sys.prefix/etc/codexctl/config.yml
        3) /etc/codexctl/config.yml
    """
    env_file = os.environ.get("CODEXCTL_CONFIG_FILE")
    if env_file:
        return [Path(env_file).expanduser().resolve()]

    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    user_cfg = (Path(xdg_home) if xdg_home else Path.home() / ".config") / "codexctl" / "config.yml"
    sp_cfg = Path(sys.prefix) / "etc" / "codexctl" / "config.yml"
    etc_cfg = Path("/etc/codexctl/config.yml")
    return [user_cfg, sp_cfg, etc_cfg]


def global_config_path() -> Path:
    """Global config file path (resolved based on search paths).

    Resolution order (first existing wins, except explicit override is returned even
    if missing to make intent visible to the user):
    - CODEXCTL_CONFIG_FILE env (returned as-is)
    - ${XDG_CONFIG_HOME:-~/.config}/codexctl/config.yml (user override)
    - sys.prefix/etc/codexctl/config.yml (pip wheels)
    - /etc/codexctl/config.yml (system default)
    If none exist, return the last path (/etc/codexctl/config.yml).
    """
    candidates = global_config_search_paths()
    # If CODEXCTL_CONFIG_FILE is set, candidates has a single element and we
    # want to return it even if it doesn't exist.
    if len(candidates) == 1:
        return candidates[0]

    for c in candidates:
        if c.is_file():
            return c.resolve()
    return candidates[-1]


def _is_root() -> bool:
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except AttributeError:
        return getpass.getuser() == "root"


def _xdg_data_home() -> Path:
    x = os.environ.get("XDG_DATA_HOME")
    return Path(x) if x else Path.home() / ".local" / "share"


def _copy_package_tree(package: str, rel_path: str, dest: Path) -> None:
    """Copy a directory tree from package resources to a filesystem path.

    Uses importlib.resources Traversable API so it works from wheels/zip installs.
    """
    root = resources.files(package) / rel_path

    def _recurse(src, dst: Path) -> None:
        dst.mkdir(parents=True, exist_ok=True)
        for child in src.iterdir():
            out = dst / child.name
            if child.is_dir():
                _recurse(child, out)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(child.read_bytes())

    _recurse(root, dest)


def _stage_scripts_into(dest: Path) -> None:
    """Stage helper scripts from package resources into dest/scripts.

    Single source of truth: codexctl/resources/scripts bundled in the wheel.
    """
    pkg_rel = "resources/scripts"
    # Replace destination directory atomically-ish
    if dest.exists():
        shutil.rmtree(dest)
    _copy_package_tree("codexctl", pkg_rel, dest)


def state_root() -> Path:
    """Writable state directory for tasks/cache/build.

    Precedence:
    - Environment variable CODEXCTL_STATE_DIR (handled first)
    - If set in global config (paths.state_root), use it.
    - Otherwise, use codexctl.paths.state_root() (FHS/XDG handling).
    """
    # Environment override should always win
    env = os.environ.get("CODEXCTL_STATE_DIR")
    if env:
        return Path(env).expanduser().resolve()

    try:
        cfg = load_global_config()
        cfg_path = (cfg.get("paths", {}) or {}).get("state_root")
        if cfg_path:
            return Path(cfg_path).expanduser().resolve()
    except Exception:
        # Be resilient to any config read error
        pass
    return _state_root_base().resolve()


def user_projects_root() -> Path:
    # Global config override
    try:
        cfg = load_global_config()
        up = (cfg.get("paths", {}) or {}).get("user_projects_root")
        if up:
            return Path(up).expanduser().resolve()
    except Exception:
        pass

    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "codexctl" / "projects"
    return Path.home() / ".config" / "codexctl" / "projects"


def build_root() -> Path:
    """
    Directory for build artifacts (generated Dockerfiles, etc.).

    Resolution order:
    - Global config: paths.build_root
    - Otherwise: state_root()/build
    """
    # Global config preferred
    try:
        cfg = load_global_config()
        paths_cfg = cfg.get("paths", {}) or {}
        br = paths_cfg.get("build_root")
        if br:
            return Path(br).expanduser().resolve()
    except Exception:
        pass

    sr = state_root()
    return (sr / "build").resolve()


# ---------- Global config (UI base port) ----------

def load_global_config() -> dict:
    cfg_path = global_config_path()
    if not cfg_path.is_file():
        return {}
    return yaml.safe_load(cfg_path.read_text()) or {}


def get_ui_base_port() -> int:
    cfg = load_global_config()
    ui_cfg = cfg.get("ui", {}) or {}
    return int(ui_cfg.get("base_port", 7860))


def get_envs_base_dir() -> Path:
    """Return the base directory for shared env mounts (codex/ssh).

    Global config (codexctl-config.yml):
      envs:
        base_dir: /var/lib/codexctl/envs

    Default: /var/lib/codexctl/envs
    """
    cfg = load_global_config()
    envs_cfg = cfg.get("envs", {}) or {}
    base = envs_cfg.get("base_dir", "/var/lib/codexctl/envs")
    return Path(str(base)).expanduser().resolve()


# ---------- Project state helpers ----------

def get_project_state(project_id: str) -> dict:
    """Return a summary of per-project infrastructure state.

    The resulting dict contains boolean flags that can be used by UIs
    (including the TUI) to give a quick overview of the project:

    - ``dockerfiles`` – True if all three Dockerfiles (L1/L2/L3) exist
      under the build root for this project.
    - ``images`` – True if podman reports that images ``<id>:l1``,
      ``<id>:l2`` and ``<id>:l3`` exist.
    - ``ssh`` – True if the project SSH directory exists and contains
      a ``config`` file.
    - ``cache`` – True if the project's cache directory exists.
    """

    project = load_project(project_id)

    # Dockerfiles: look in the same location generate_dockerfiles writes to.
    stage_dir = build_root() / project.id
    dockerfiles = [
        stage_dir / "L1.Dockerfile",
        stage_dir / "L2.Dockerfile",
        stage_dir / "L3.Dockerfile",
    ]
    has_dockerfiles = all(p.is_file() for p in dockerfiles)

    # Images: rely on podman image tags created by build_images().
    has_images = False
    try:
        required_tags = [f"{project.id}:l1", f"{project.id}:l2", f"{project.id}:l3"]
        ok = True
        for tag in required_tags:
            # ``podman image exists`` exits with 0 when the image is present.
            result = subprocess.run(
                ["podman", "image", "exists", tag],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                ok = False
                break
        has_images = ok
    except (FileNotFoundError, OSError):  # podman missing or not usable
        has_images = False

    # SSH: same resolution logic as init_project_ssh(). Consider SSH
    # "ready" when the directory and its config file exist.
    ssh_dir = project.ssh_host_dir or (get_envs_base_dir() / f"_ssh-config-{project.id}")
    ssh_dir = Path(ssh_dir).expanduser().resolve()
    has_ssh = ssh_dir.is_dir() and (ssh_dir / "config").is_file()

    # Cache: a mirror bare repo initialized by init_project_cache(). We
    # treat existence of the directory as "cache present".
    cache_dir = project.cache_path
    has_cache = cache_dir.is_dir()

    return {
        "dockerfiles": has_dockerfiles,
        "images": has_images,
        "ssh": has_ssh,
        "cache": has_cache,
    }


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
    target_dir.mkdir(parents=True, exist_ok=True)

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
                config_text = _render_template(user_template_path, variables)
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

    # Best-effort permissions and ownership for container dev user access.
    try:
        os.chmod(target_dir, 0o700)
        if priv_path.exists():
            os.chmod(priv_path, 0o600)
        if pub_path.exists():
            os.chmod(pub_path, 0o644)
        if cfg_path.exists():
            os.chmod(cfg_path, 0o644)
    except Exception:
        pass
    try:
        dev_uid = 1000
        dev_gid = 1000
        os.chown(target_dir, dev_uid, dev_gid)
        for p in (priv_path, pub_path, cfg_path):
            if p.exists():
                os.chown(p, dev_uid, dev_gid)
    except Exception:
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


# ---------- Project model ----------

@dataclass
class Project:
    id: str
    security_class: str          # "online" | "gatekept"
    upstream_url: Optional[str]
    default_branch: str
    root: Path

    tasks_root: Path             # workspace dirs
    cache_path: Path             # future cache
    staging_root: Optional[Path] # gatekept only

    ssh_key_name: Optional[str]
    ssh_host_dir: Optional[Path]
    codex_config_dir: Optional[Path]
    # Optional path to an SSH config template (user-provided). If set, ssh-init
    # will render this template to the shared .ssh/config. Tokens supported:
    #   {{IDENTITY_FILE}}  → absolute path of the generated private key
    #   {{KEY_NAME}}       → filename of the generated key (no .pub)
    #   {{PROJECT_ID}}     → project id
    ssh_config_template: Optional[Path] = None
    # Whether to mount SSH credentials inside online containers. Default: True.
    ssh_mount_in_online: bool = True


def _effective_ssh_key_name(project: Project, key_type: str = "ed25519") -> str:
    """Return the SSH key filename that should be used for this project.

    Precedence:
      1. Explicit `ssh.key_name` from project.yml (project.ssh_key_name)
      2. Derived default: id_<type>_<project_id>, e.g. id_ed25519_myproj

    This helper centralizes the default so ssh-init, container env (SSH_KEY_NAME)
    and host-side git helpers all agree even when project.yml omits ssh.key_name.
    """

    if project.ssh_key_name:
        return project.ssh_key_name
    algo = "ed25519" if key_type == "ed25519" else "rsa"
    return f"id_{algo}_{project.id}"


def _find_project_root(project_id: str) -> Path:
    user_root = user_projects_root() / project_id
    sys_root = config_root() / project_id
    if (user_root / "project.yml").is_file():
        return user_root
    if (sys_root / "project.yml").is_file():
        return sys_root
    raise SystemExit(f"Project '{project_id}' not found in {user_root} or {sys_root}")


# ---------- Project listing ----------
def list_projects() -> list[Project]:
    """
    Discover all projects (user + system) and return them as Project objects.
    User projects override system ones with the same id.
    """
    ids: set[str] = set()

    # Collect IDs from user and system project dirs
    for root in (user_projects_root(), config_root()):
        if not root.is_dir():
            continue
        for d in root.iterdir():
            if not d.is_dir():
                continue
            if (d / "project.yml").is_file():
                ids.add(d.name)

    projects: list[Project] = []
    for pid in sorted(ids):
        # load_project will automatically prefer user over system config
        try:
            projects.append(load_project(pid))
        except SystemExit:
            # if a project is broken, skip it rather than crashing the listing
            continue
    return projects


def load_project(project_id: str) -> Project:
    root = _find_project_root(project_id)
    cfg_path = root / "project.yml"
    if not cfg_path.is_file():
        raise SystemExit(f"Missing project.yml in {root}")
    cfg = yaml.safe_load(cfg_path.read_text()) or {}

    proj_cfg = cfg.get("project", {}) or {}
    git_cfg = cfg.get("git", {}) or {}
    ssh_cfg = cfg.get("ssh", {}) or {}
    codex_cfg = cfg.get("codex", {}) or {}
    tasks_cfg = cfg.get("tasks", {}) or {}
    cache_cfg = cfg.get("cache", {}) or {}
    gate_cfg = cfg.get("gatekeeping", {}) or {}

    pid = proj_cfg.get("id", project_id)
    sec = proj_cfg.get("security_class", "online")

    sr = state_root()
    tasks_root = Path(tasks_cfg.get("root", sr / "tasks" / pid)).resolve()
    cache_path = Path(cache_cfg.get("path", sr / "cache" / f"{pid}.git")).resolve()

    staging_root: Optional[Path] = None
    if sec == "gatekept":
        # Default to build_root unless explicitly configured in project.yml
        staging_root = Path(gate_cfg.get("staging_root", build_root() / pid)).resolve()

    upstream_url = git_cfg.get("upstream_url")
    default_branch = git_cfg.get("default_branch", "main")

    ssh_key_name = ssh_cfg.get("key_name")
    ssh_host_dir = Path(ssh_cfg.get("host_dir")).expanduser().resolve() if ssh_cfg.get("host_dir") else None

    codex_config_dir = Path(codex_cfg.get("config_dir")).expanduser().resolve() if codex_cfg.get("config_dir") else None

    # Optional: ssh.config_template (path to a template file). If relative, it's relative to the project root.
    ssh_cfg_template_path: Optional[Path] = None
    if ssh_cfg.get("config_template"):
        cfg_t = Path(str(ssh_cfg.get("config_template")))
        if not cfg_t.is_absolute():
            cfg_t = (root / cfg_t)
        ssh_cfg_template_path = cfg_t.expanduser().resolve()

    # Optional flag: ssh.mount_in_online (default true)
    ssh_mount_in_online = bool(ssh_cfg.get("mount_in_online", True))

    p = Project(
        id=pid,
        security_class=sec,
        upstream_url=upstream_url,
        default_branch=default_branch,
        root=root.resolve(),
        tasks_root=tasks_root,
        cache_path=cache_path,
        staging_root=staging_root,
        ssh_key_name=ssh_key_name,
        ssh_host_dir=ssh_host_dir,
        codex_config_dir=codex_config_dir,
        ssh_config_template=ssh_cfg_template_path,
        ssh_mount_in_online=ssh_mount_in_online,
    )
    return p


# ---------- Dockerfile gen & build ----------

def _ensure_dir(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)


def _render_template(template_path: Path, variables: dict) -> str:
    content = template_path.read_text()
    # Extremely simple token replacement: {{VAR}} → variables["VAR"]
    for k, v in variables.items():
        content = content.replace(f"{{{{{k}}}}}", str(v))
    return content


def generate_dockerfiles(project_id: str) -> None:
    project = load_project(project_id)

    # Load templates from package resources (codexctl/resources/templates). Use
    # importlib.resources Traversable API so it works from wheels/zip too.
    tmpl_pkg = resources.files("codexctl") / "resources" / "templates"
    l1_txt = (tmpl_pkg / "l1.dev.Dockerfile.template").read_text()
    l2_txt = (tmpl_pkg / "l2.codex-agent.Dockerfile.template").read_text()
    l3_txt = (tmpl_pkg / "l3.codexui.Dockerfile.template").read_text()

    out_dir = build_root() / project.id
    _ensure_dir(out_dir)

    # Read additional docker-related settings directly from the project.yml
    docker_cfg: dict = {}
    try:
        cfg = yaml.safe_load((project.root / "project.yml").read_text()) or {}
        docker_cfg = cfg.get("docker", {}) or {}
    except Exception:
        docker_cfg = {}

    # Resolve optional user snippet: prefer inline over file
    user_snippet = ""
    us_inline = docker_cfg.get("user_snippet_inline")
    if isinstance(us_inline, str) and us_inline.strip():
        user_snippet = us_inline
    else:
        us_file = docker_cfg.get("user_snippet_file")
        if isinstance(us_file, str) and us_file:
            us_path = Path(us_file)
            if not us_path.is_absolute():
                us_path = project.root / us_file
            try:
                if us_path.is_file():
                    user_snippet = us_path.read_text()
            except Exception:
                user_snippet = ""

    # SSH_KEY_NAME inside containers should mirror the filename that ssh-init
    # generated (or will generate) for this project. We assume the default
    # key_type (ed25519) here, which matches init_project_ssh's default.
    effective_ssh_key_name = _effective_ssh_key_name(project, key_type="ed25519")

    variables = {
        "PROJECT_ID": project.id,
        "SECURITY_CLASS": project.security_class,
        "UPSTREAM_URL": project.upstream_url or "",
        "DEFAULT_BRANCH": project.default_branch,
        # Template-specific extras
        "BASE_IMAGE": str(docker_cfg.get("base_image", "ubuntu:24.04")),
        "SSH_KEY_NAME": effective_ssh_key_name,
        "CODE_REPO_DEFAULT": project.upstream_url or "",
        "USER_SNIPPET": user_snippet,
    }

    # Apply simple token replacement
    for name, content in (
        ("L1.Dockerfile", l1_txt),
        ("L2.Dockerfile", l2_txt),
        ("L3.Dockerfile", l3_txt),
    ):
        for k, v in variables.items():
            content = content.replace(f"{{{{{k}}}}}", str(v))
        (out_dir / name).write_text(content)

    # Stage auxiliary scripts into build context so Dockerfile COPY works.
    try:
        _stage_scripts_into(out_dir / "scripts")
    except Exception:
        # Non-fatal: some templates may not need scripts
        pass

    print(f"Generated Dockerfiles in {out_dir}")


def build_images(project_id: str) -> None:
    project = load_project(project_id)
    stage_dir = build_root() / project.id

    l1 = stage_dir / "L1.Dockerfile"
    l2 = stage_dir / "L2.Dockerfile"
    l3 = stage_dir / "L3.Dockerfile"

    if not l1.is_file() or not l2.is_file() or not l3.is_file():
        raise SystemExit("Dockerfiles are missing. Run 'codexctl generate <project>' first.")

    # Build commands (using podman). Real implementation would pass context and tags.
    # Build with the project-specific build directory as context so COPY scripts/ works
    context_dir = str(stage_dir)

    # Read docker.base_image from project.yml for L1 only (handled in templates
    # at generation time). For L2/L3 we must base FROM the just-built L1 image
    # so that init-ssh-and-repo.sh (and other assets) are available at runtime.
    # Therefore, we always pass BASE_IMAGE="<project_id>:l1" when building L2/L3.
    l2l3_base_image = f"{project.id}:l1"

    cmds = [
        ["podman", "build", "-f", str(l1), "-t", f"{project.id}:l1", context_dir],
        # L2 and L3 use ARG BASE_IMAGE before FROM, so we must pass --build-arg
        [
            "podman", "build",
            "-f", str(l2),
            "--build-arg", f"BASE_IMAGE={l2l3_base_image}",
            "-t", f"{project.id}:l2",
            context_dir,
        ],
        [
            "podman", "build",
            "-f", str(l3),
            "--build-arg", f"BASE_IMAGE={l2l3_base_image}",
            "-t", f"{project.id}:l3",
            context_dir,
        ],
    ]
    for cmd in cmds:
        print("$", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True)
        except FileNotFoundError:
            raise SystemExit("podman not found; please install podman")
        except subprocess.CalledProcessError as e:
            raise SystemExit(f"Build failed: {e}")


# ---------- Tasks ----------

def _tasks_meta_dir(project_id: str) -> Path:
    return state_root() / "projects" / project_id / "tasks"


def _log_debug(message: str) -> None:
    """Append a simple debug line to the codexctl library log.

    This is intentionally very small and best-effort so it never interferes
    with normal CLI or TUI behavior. It can be used to compare behavior
    between different frontends (e.g. CLI vs TUI) when calling the shared
    helpers in this module.
    """

    try:
        from datetime import datetime as _dt
        from pathlib import Path as _Path

        log_path = _Path("/tmp/codexctl-lib.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = _dt.now().isoformat(timespec="seconds")
        with log_path.open("a", encoding="utf-8") as _f:
            _f.write(f"[codexctl DEBUG] {ts} {message}\n")
    except Exception:
        # Logging must never change behavior of library code.
        pass


def task_new(project_id: str) -> None:
    project = load_project(project_id)
    tasks_root = project.tasks_root
    _ensure_dir(tasks_root)
    meta_dir = _tasks_meta_dir(project.id)
    _ensure_dir(meta_dir)

    # Simple ID: numeric increment
    existing = sorted([p.stem for p in meta_dir.glob("*.yml") if p.stem.isdigit()], key=int)
    next_id = str(int(existing[-1]) + 1 if existing else 1)

    ws = tasks_root / next_id
    _ensure_dir(ws)

    meta = {
        "task_id": next_id,
        "status": "created",
        "mode": None,
        "workspace": str(ws),
        "ui_port": None,
    }
    (meta_dir / f"{next_id}.yml").write_text(yaml.safe_dump(meta))
    print(f"Created task {next_id} in {ws}")


def get_tasks(project_id: str, reverse: bool = False) -> list[dict]:
    meta_dir = _tasks_meta_dir(project_id)
    tasks: list[dict] = []
    if not meta_dir.is_dir():
        return tasks
    for f in meta_dir.glob("*.yml"):
        try:
            tasks.append(yaml.safe_load(f.read_text()) or {})
        except Exception:
            continue
    tasks.sort(key=lambda d: int(d.get("task_id", 0)), reverse=reverse)
    return tasks


def task_list(project_id: str) -> None:
    tasks = get_tasks(project_id)
    if not tasks:
        print("No tasks found")
        return
    for t in tasks:
        tid = t.get("task_id", "?")
        status = t.get("status", "unknown")
        mode = t.get("mode")
        port = t.get("ui_port")
        extra = []
        if mode:
            extra.append(f"mode={mode}")
        if port:
            extra.append(f"port={port}")
        extra_s = f" [{'; '.join(extra)}]" if extra else ""
        print(f"- {tid}: {status}{extra_s}")


# ---------- Pod/port helpers ----------

def _is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _collect_all_ui_ports() -> set[int]:
    # Scan all task metas for any project
    root = state_root() / "projects"
    ports: set[int] = set()
    if not root.is_dir():
        return ports
    for proj_dir in root.iterdir():
        tdir = proj_dir / "tasks"
        if not tdir.is_dir():
            continue
        for f in tdir.glob("*.yml"):
            try:
                meta = yaml.safe_load(f.read_text()) or {}
            except Exception:
                continue
            port = meta.get("ui_port")
            if isinstance(port, int):
                ports.add(port)
    return ports


def _assign_ui_port() -> int:
    used = _collect_all_ui_ports()
    base = get_ui_base_port()
    port = base
    max_tries = 200
    tries = 0
    while tries < max_tries:
        if port not in used and _is_port_free(port):
            return port
        port += 1
        tries += 1
    raise SystemExit("No free UI ports available")


def _build_task_env_and_volumes(project: Project, task_id: str) -> tuple[dict, list[str]]:
    """Compose environment and volume mounts for a task container.

    - Mount per-task workspace subdir to /workspace (host-explorable).
    - Mount shared codex config dir to /home/dev/.codex (read-write).
    - Mount shared Claude config dir to /home/dev/.claude (read-write).
    - Optionally mount per-project SSH config dir to /home/dev/.ssh (read-write).
    - Provide REPO_ROOT and git info for the init script.
    """
    # Per-task workspace directory as a subdirectory of the task dir
    task_dir = project.tasks_root / str(task_id)
    repo_dir = task_dir / "workspace"
    repo_dir.mkdir(parents=True, exist_ok=True)

    # Shared env mounts
    envs_base = get_envs_base_dir()
    codex_host_dir = envs_base / "_codex-config"
    claude_host_dir = envs_base / "_claude-config"
    # Prefer project-configured SSH host dir if set
    ssh_host_dir = project.ssh_host_dir or (envs_base / f"_ssh-config-{project.id}")
    # Ensure codex dir exists so the mount works
    codex_host_dir.mkdir(parents=True, exist_ok=True)
    claude_host_dir.mkdir(parents=True, exist_ok=True)

    env = {
        "PROJECT_ID": project.id,
        "TASK_ID": task_id,
        # Tell init script where to clone/sync the repo
        "REPO_ROOT": "/workspace",
        # Default reset mode is none; allow overriding via container env if needed
        "GIT_RESET_MODE": os.environ.get("CODEXCTL_GIT_RESET_MODE", "none"),
        # Keep Claude Code config under the shared mount regardless of HOME.
        "CLAUDE_CONFIG_DIR": "/home/dev/.claude",
    }

    volumes: list[str] = []
    # Per-task workspace mount
    volumes.append(f"{repo_dir}:/workspace:Z")

    # Shared codex credentials/config
    volumes.append(f"{codex_host_dir}:/home/dev/.codex:Z")
    # Shared Claude credentials/config
    volumes.append(f"{claude_host_dir}:/home/dev/.claude:Z")

    # Security mode specific wiring
    cache_repo = project.cache_path
    cache_parent = cache_repo.parent
    # Mount point inside container for the cache
    cache_mount_inside = "/git-cache/cache.git"

    if project.security_class == "gatekept":
        # In gatekept mode, hide upstream and SSH. Use the host cache as the only remote.
        if not cache_repo.exists():
            raise SystemExit(
                f"Git cache missing for project '{project.id}'.\n"
                f"Expected at: {cache_repo}\n"
                f"Run 'codexctl cache-init {project.id}' to create/update the local mirror."
            )

        # Ensure parent exists for mount consistency (cache should already exist)
        cache_parent.mkdir(parents=True, exist_ok=True)
        # Mount cache read-write so tasks can push branches for review
        volumes.append(f"{cache_repo}:{cache_mount_inside}:Z")
        env["CODE_REPO"] = f"file://{cache_mount_inside}"
        env["GIT_BRANCH"] = project.default_branch or "main"
        # No SSH mount in gatekept
    else:
        # Online mode: clone from cache if present, then set upstream to real URL
        if cache_repo.exists():
            cache_parent.mkdir(parents=True, exist_ok=True)
            # Mount cache read-only
            volumes.append(f"{cache_repo}:{cache_mount_inside}:Z,ro")
            env["CLONE_FROM"] = f"file://{cache_mount_inside}"
        if project.upstream_url:
            env["CODE_REPO"] = project.upstream_url
            env["GIT_BRANCH"] = project.default_branch or "main"
        # Optional SSH config mount in online mode (configurable)
        if project.ssh_mount_in_online and ssh_host_dir.is_dir():
            volumes.append(f"{ssh_host_dir}:/home/dev/.ssh:Z")

    return env, volumes


# ---------- Git cache initialization (host-side) ----------

def _git_env_with_ssh(project: Project) -> dict:
    """Return an env that forces git to use the project's SSH config only.

    - Sets GIT_SSH_COMMAND to use the per-project ssh config via `-F <config>`.
    - Adds `-o IdentitiesOnly=yes` to prevent fallback to keys in ~/.ssh or agent.
    - If a specific private key exists in the project ssh dir (derived from
      project.ssh_key_name), also adds `-o IdentityFile=<that key>` explicitly.

    If the ssh host dir or config is missing, we return the current env.
    """
    env = os.environ.copy()
    ssh_dir = project.ssh_host_dir or (get_envs_base_dir() / f"_ssh-config-{project.id}")
    cfg = Path(ssh_dir) / "config"
    if cfg.is_file():
        ssh_cmd = ["ssh", "-F", str(cfg), "-o", "IdentitiesOnly=yes"]
        # Prefer explicit IdentityFile if we can resolve it. Use the same
        # effective key name logic as ssh-init / containers so that even when
        # ssh.key_name is omitted we still look for the derived default
        # (id_<type>_<project_id>), while keeping this best-effort.
        effective_name = _effective_ssh_key_name(project, key_type="ed25519")
        key_path = Path(ssh_dir) / effective_name
        if key_path.is_file():
            ssh_cmd += ["-o", f"IdentityFile={key_path}"]
        env["GIT_SSH_COMMAND"] = " ".join(map(str, ssh_cmd))
        # Also clear SSH_AUTH_SOCK so agent identities are not considered
        env["SSH_AUTH_SOCK"] = ""
    return env


def init_project_cache(project_id: str, force: bool = False) -> dict:
    """Create or update a host-side git mirror cache for a project.

    - Uses the project's SSH configuration (from ssh-init) via GIT_SSH_COMMAND.
    - If cache doesn't exist or --force is given, performs a fresh `git clone --mirror`.
    - Otherwise, runs `git remote update --prune` to sync.

    Returns a dict with keys: path, upstream_url, created (bool).
    """
    project = load_project(project_id)
    if not project.upstream_url:
        raise SystemExit("Project has no git.upstream_url configured")

    cache_dir = project.cache_path
    cache_dir.parent.mkdir(parents=True, exist_ok=True)

    # Determine if upstream requires SSH and ensure we only use the project's SSH dir
    upstream = project.upstream_url
    is_ssh_upstream = False
    try:
        is_ssh_upstream = upstream.startswith("git@") or upstream.startswith("ssh://")
    except Exception:
        is_ssh_upstream = False

    # Resolve the project's ssh dir and config path (created by ssh-init)
    ssh_dir = project.ssh_host_dir or (get_envs_base_dir() / f"_ssh-config-{project.id}")
    ssh_cfg_path = Path(ssh_dir) / "config"

    if is_ssh_upstream:
        # For SSH upstreams, require the project-specific config; do NOT fall back to ~/.ssh
        if not ssh_cfg_path.is_file():
            raise SystemExit(
                "SSH upstream detected but project SSH config is missing.\n"
                f"Expected SSH config at: {ssh_cfg_path}\n"
                f"Run 'codexctl ssh-init {project.id}' first to generate keys and config."
            )

    # Build git environment that forces use of the project's SSH config (if present)
    env = _git_env_with_ssh(project)

    created = False
    if force and cache_dir.exists():
        # Remove to ensure clean mirror
        try:
            if cache_dir.is_dir():
                shutil.rmtree(cache_dir)
        except Exception:
            pass

    if not cache_dir.exists():
        # Create a mirror clone
        cmd = ["git", "clone", "--mirror", project.upstream_url, str(cache_dir)]
        try:
            subprocess.run(cmd, check=True, env=env)
        except FileNotFoundError:
            raise SystemExit("git not found on host; please install git")
        except subprocess.CalledProcessError as e:
            raise SystemExit(f"git clone --mirror failed: {e}")
        created = True
    else:
        # Update existing mirror
        try:
            subprocess.run(["git", "-C", str(cache_dir), "remote", "update", "--prune"], check=True, env=env)
        except subprocess.CalledProcessError as e:
            raise SystemExit(f"git remote update failed: {e}")

    return {"path": str(cache_dir), "upstream_url": project.upstream_url, "created": created}


def _gpu_run_args(project: Project) -> list[str]:
    """Return additional podman run args to enable NVIDIA GPU if configured.

    Per-project only: GPUs are enabled exclusively by the project's project.yml.
    Default is disabled. Global config and environment variables are ignored.

    project.yml example:
      run:
        gpus: all   # or true

    When enabled, we pass a combination that works with Podman +
    nvidia-container-toolkit (recent versions):
      --device nvidia.com/gpu=all
      -e NVIDIA_VISIBLE_DEVICES=all
      -e NVIDIA_DRIVER_CAPABILITIES=all
      (optional) --hooks-dir=/usr/share/containers/oci/hooks.d if it exists
    """
    # Project-level setting from project.yml (only source of truth)
    enabled = False
    try:
        proj_cfg = yaml.safe_load((project.root / "project.yml").read_text()) or {}
        run_cfg = (proj_cfg.get("run", {}) or {})
        gpus = run_cfg.get("gpus", run_cfg.get("gpu"))
        if isinstance(gpus, str):
            enabled = gpus.lower() == "all"
        elif isinstance(gpus, bool):
            enabled = gpus
    except Exception:
        enabled = False

    if not enabled:
        return []

    args: list[str] = [
        "--device", "nvidia.com/gpu=all",
        "-e", "NVIDIA_VISIBLE_DEVICES=all",
        "-e", "NVIDIA_DRIVER_CAPABILITIES=all",
    ]
    hooks_dir = Path("/usr/share/containers/oci/hooks.d")
    if hooks_dir.is_dir():
        args.extend(["--hooks-dir", str(hooks_dir)])
    return args


def _check_mode(meta: dict, expected: str) -> None:
    mode = meta.get("mode")
    if mode and mode != expected:
        raise SystemExit(f"Task already ran in mode '{mode}', cannot run in '{expected}'")


def _stop_task_containers(project: "Project", task_id: str) -> None:
    """Best-effort removal of any containers associated with a task.

    We intentionally ignore most errors here: task deletion should succeed
    even if podman isn't installed, the containers are already gone, or the
    container names never existed. This helper is used when deleting a
    task's workspace/metadata to avoid leaving behind containers that would
    later conflict with a new task reusing the same ID.

    We use ``podman rm -f`` rather than ``podman stop`` to make teardown
    deterministic and avoid hangs waiting for graceful shutdown inside the
    container. The task itself is already being deleted at this point, so
    a forceful remove is acceptable and keeps state consistent.
    """

    # The naming scheme is kept in sync with task_run_cli/task_run_ui.
    names = [
        f"{project.id}-cli-{task_id}",
        f"{project.id}-ui-{task_id}",
    ]

    for name in names:
        try:
            _log_debug(f"stop_containers: podman rm -f {name} (start)")
            # "podman rm -f" force-removes the container even if it is
            # currently running. If the container does not exist this will
            # fail, but we treat that as a non-fatal condition and simply
            # continue.
            subprocess.run(
                ["podman", "rm", "-f", name],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _log_debug(f"stop_containers: podman rm -f {name} (done)")
        except FileNotFoundError:
            # podman not installed; nothing we can do here.
            _log_debug("stop_containers: podman not found; skipping all")
            break


def task_delete(project_id: str, task_id: str) -> None:
    """Delete a task's workspace, metadata, and any associated containers.

    This mirrors the behavior used by the TUI when deleting a task, but is
    exposed here so both CLI and TUI share the same logic. Containers are
    stopped best-effort via podman using the naming scheme
    "<project.id>-<mode>-<task_id>".
    """

    _log_debug(f"task_delete: start project_id={project_id} task_id={task_id}")

    project = load_project(project_id)
    _log_debug("task_delete: loaded project")

    # Workspace lives under the project's tasks_root using the numeric ID.
    workspace = project.tasks_root / str(task_id)

    # Metadata lives in the per-project tasks state dir.
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    _log_debug(f"task_delete: workspace={workspace} meta_path={meta_path}")

    # Stop any matching containers first to avoid name conflicts if a new
    # task is later created with the same ID.
    _log_debug("task_delete: calling _stop_task_containers")
    _stop_task_containers(project, str(task_id))
    _log_debug("task_delete: _stop_task_containers returned")

    if workspace.is_dir():
        _log_debug("task_delete: removing workspace directory")
        shutil.rmtree(workspace)
        _log_debug("task_delete: workspace directory removed")

    if meta_path.is_file():
        _log_debug("task_delete: removing metadata file")
        meta_path.unlink()
        _log_debug("task_delete: metadata file removed")

    _log_debug("task_delete: finished")


def task_run_cli(project_id: str, task_id: str) -> None:
    project = load_project(project_id)
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text()) or {}
    _check_mode(meta, "cli")

    env, volumes = _build_task_env_and_volumes(project, task_id)

    # Run detached and keep the container alive so users can exec into it later
    cmd = ["podman", "run", "--rm", "-d"]
    cmd += _gpu_run_args(project)
    # Volumes
    for v in volumes:
        cmd += ["-v", v]
    # Environment
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    # Name, workdir, image and command
    cmd += [
        "--name", f"{project.id}-cli-{task_id}",
        "-w", "/workspace",
        f"{project.id}:l2",
        # Ensure init runs and then keep the container alive even without a TTY
        # init-ssh-and-repo.sh now prints a readiness marker we can watch for
        "bash", "-lc", "init-ssh-and-repo.sh; echo __CLI_READY__; tail -f /dev/null",
    ]
    print("$", " ".join(map(str, cmd)))
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE)
    except FileNotFoundError:
        raise SystemExit("podman not found; please install podman")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Run failed: {e}")

    # Stream initial logs until ready marker is seen (or timeout), then detach
    _stream_initial_logs(
        container_name=f"{project.id}-cli-{task_id}",
        timeout_sec=60.0,
        ready_check=lambda line: "__CLI_READY__" in line or ">> init complete" in line,
    )

    # Mark task as started (not completed) for CLI mode
    meta["status"] = "running"
    meta["mode"] = "cli"
    meta_path.write_text(yaml.safe_dump(meta))

    print(
        "\nCLI container is running in the background.\n"
        f"- Name: {project.id}-cli-{task_id}\n"
        f"- To enter: podman exec -it {project.id}-cli-{task_id} bash\n"
        f"- To stop:  podman stop {project.id}-cli-{task_id}\n"
    )


def task_run_ui(project_id: str, task_id: str) -> None:
    project = load_project(project_id)
    meta_dir = _tasks_meta_dir(project.id)
    meta_path = meta_dir / f"{task_id}.yml"
    if not meta_path.is_file():
        raise SystemExit(f"Unknown task {task_id}")
    meta = yaml.safe_load(meta_path.read_text()) or {}
    _check_mode(meta, "ui")

    port = meta.get("ui_port")
    if not isinstance(port, int):
        port = _assign_ui_port()
        meta["ui_port"] = port
        meta_path.write_text(yaml.safe_dump(meta))

    env, volumes = _build_task_env_and_volumes(project, task_id)

    container_name = f"{project.id}-ui-{task_id}"

    # Start UI in background and return terminal when it's reachable
    cmd = ["podman", "run", "--rm", "-d", "-p", f"127.0.0.1:{port}:7860"]
    cmd += _gpu_run_args(project)
    # Volumes
    for v in volumes:
        cmd += ["-v", v]
    # Environment
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += [
        "--name", container_name,
        "-w", "/workspace",
        f"{project.id}:l3",
    ]
    print("$", " ".join(map(str, cmd)))
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE)
    except FileNotFoundError:
        raise SystemExit("podman not found; please install podman")
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"Run failed: {e}")

    # Stream initial logs and detach once the Codex UI server reports that it
    # is actually running. We intentionally rely on a *log marker* here
    # instead of just probing the TCP port, because podman exposes the host port
    # regardless of the state of the routed guest port.
    # conflicts 
    # Codex UI currently prints stable lines when the server is ready, e.g.:
    #   "Logging Codex UI activity to /var/log/codexui.log"
    #   "Codex UI (SDK streaming) on http://0.0.0.0:7860 — repo /workspace"
    #
    # We treat the appearance of either of these as the readiness signal.
    def _ui_ready(line: str) -> bool:
        line = line.strip()
        if not line:
            return False

        # Primary marker: the main startup banner emitted by Codex UI when
        # the HTTP server is ready to accept connections.
        if "Codex UI (" in line:
            return True

        # Secondary marker: log redirection message that currently appears at
        # roughly the same time as the banner above.
        if "Logging Codex UI activity" in line:
            return True

        return False

    # Follow logs until either the Codex UI readiness marker is seen or the
    # container exits. We deliberately do *not* time out here: as long as the
    # init script keeps making progress, the user sees the live logs and can
    # decide to Ctrl+C if it hangs.
    ready = _stream_initial_logs(
        container_name=container_name,
        timeout_sec=None,
        ready_check=_ui_ready,
    )

    # After log streaming stops, check whether the container is actually
    # still running. This prevents false "UI is up" messages in cases where
    # the UI process failed to start (e.g. Node error) and the container
    # exited before emitting the readiness marker.
    running = _is_container_running(container_name)

    if ready and running:
        print("\n\n>> codexctl: ")
        print(f"UI container is up, routed to: http://127.0.0.1:{port}")
    elif not running:
        print(
            "UI container exited before the web UI became reachable. "
            "Check the container logs for errors."
        )
        print(
            f"- Last known name: {container_name}\n"
            f"- Check logs (if still available): podman logs {container_name}\n"
            f"- You may need to re-run: codexctl task run-ui {project.id} {task_id}"
        )
        # Exit with non-zero status to signal that the UI did not start.
        raise SystemExit(1)

    print(
        f"- Name: {container_name}\n"
        f"- Check logs: podman logs -f {container_name}\n"
        f"- Stop:       podman stop {container_name}"
    )


def _is_container_running(container_name: str) -> bool:
    """Return True if a podman container with the given name is running.

    This uses `podman inspect` and treats missing containers or any
    inspection error as "not running".
    """
    try:
        out = subprocess.check_output(
            ["podman", "inspect", "-f", "{{.State.Running}}", container_name],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return out.lower() == "true"


def _stream_initial_logs(container_name: str, timeout_sec: Optional[float], ready_check) -> bool:
    """Follow container logs and detach when ready, timed out, or container exits.

    - container_name: podman container name.
    - timeout_sec: maximum seconds to follow logs. If ``None``, there is no
      time-based cutoff and we only stop when either the ready condition is
      met or the container exits.
    - ready_check: callable(line:str)->bool that returns True when ready. It will
      be evaluated for each incoming log line; for UI case it may ignore line
      content and probe external readiness.

    Returns True if a ready condition was met, False on timeout or if logs
    ended without ever becoming ready.
    """
    try:
        proc = subprocess.Popen(
            ["podman", "logs", "-f", container_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception:
        return False

    start = time.time()
    ready = False
    try:
        assert proc.stdout is not None
        while True:
            # Stop if timeout (when enabled)
            if timeout_sec is not None and (time.time() - start > timeout_sec):
                break
            # If process already ended, stop
            if proc.poll() is not None:
                break
            # Wait for a line (non-blocking with select)
            rlist, _, _ = select.select([proc.stdout], [], [], 0.5)
            if not rlist:
                # Even without a new line, allow external readiness checks
                if ready_check(""):
                    ready = True
                    break
                continue
            line = proc.stdout.readline()
            if not line:
                continue
            # Echo the line to the user's terminal
            try:
                sys.stdout.write(line)
                sys.stdout.flush()
            except Exception:
                pass
            # Check readiness based on the line content
            try:
                if ready_check(line):
                    ready = True
                    break
            except Exception:
                # Ignore errors in readiness checks
                pass
    finally:
        # Stop following logs
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
        except Exception:
            pass
    return ready


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
    # Ensure codex dir exists so the mount works
    codex_host_dir.mkdir(parents=True, exist_ok=True)

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
