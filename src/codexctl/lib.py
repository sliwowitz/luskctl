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

    # Resolve optional user snippet
    user_snippet = ""
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

    variables = {
        "PROJECT_ID": project.id,
        "SECURITY_CLASS": project.security_class,
        "UPSTREAM_URL": project.upstream_url or "",
        "DEFAULT_BRANCH": project.default_branch,
        # Template-specific extras
        "BASE_IMAGE": str(docker_cfg.get("base_image", "ubuntu:24.04")),
        "SSH_KEY_NAME": project.ssh_key_name or "",
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
    - Optionally mount per-project SSH config dir to /home/dev/.ssh (read-only).
    - Provide REPO_ROOT and git info for the init script.
    """
    # Per-task workspace directory as a subdirectory of the task dir
    task_dir = project.tasks_root / str(task_id)
    repo_dir = task_dir / "workspace"
    repo_dir.mkdir(parents=True, exist_ok=True)

    # Shared env mounts
    envs_base = get_envs_base_dir()
    codex_host_dir = envs_base / "_codex-config"
    ssh_host_dir = envs_base / f"_ssh-config-{project.id}"
    # Ensure codex dir exists so the mount works
    codex_host_dir.mkdir(parents=True, exist_ok=True)

    env = {
        "PROJECT_ID": project.id,
        "TASK_ID": task_id,
        # Tell init script where to clone/sync the repo
        "REPO_ROOT": "/workspace",
    }
    if project.upstream_url:
        env["CODE_REPO"] = project.upstream_url
        env["GIT_BRANCH"] = project.default_branch or "main"
        # Default reset mode is none; allow overriding via container env if needed
        env["GIT_RESET_MODE"] = os.environ.get("CODEXCTL_GIT_RESET_MODE", "none")

    volumes: list[str] = []
    # Per-task workspace mount
    volumes.append(f"{repo_dir}:/workspace:Z")

    # Shared codex credentials/config
    volumes.append(f"{codex_host_dir}:/home/dev/.codex:Z")

    # Optional SSH config (read-only) if present
    if ssh_host_dir.is_dir():
        volumes.append(f"{ssh_host_dir}:/home/dev/.ssh:Z,ro")

    return env, volumes


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
        "--name", f"{project.id}-ui-{task_id}",
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

    # Stream initial logs while probing the UI port; detach on ready or timeout
    addr = ("127.0.0.1", int(port))
    def _ui_ready(_: str) -> bool:
        try:
            with socket.create_connection(addr, timeout=0.5):
                return True
        except OSError:
            return False

    ready = _stream_initial_logs(
        container_name=f"{project.id}-ui-{task_id}",
        timeout_sec=30.0,
        ready_check=_ui_ready,
    )

    if ready:
        print(f"UI is up: http://127.0.0.1:{port} (container running in background)")
    else:
        print(
            f"UI container started but not reachable on http://127.0.0.1:{port} yet. "
            "It may still be initializing."
        )

    print(
        f"- Name: {project.id}-ui-{task_id}\n"
        f"- Check logs: podman logs -f {project.id}-ui-{task_id}\n"
        f"- Stop:       podman stop {project.id}-ui-{task_id}"
    )


def _stream_initial_logs(container_name: str, timeout_sec: float, ready_check) -> bool:
    """Follow initial container logs and detach when ready or timed out.

    - container_name: podman container name.
    - timeout_sec: maximum seconds to follow logs.
    - ready_check: callable(line:str)->bool that returns True when ready. It will
      be evaluated for each incoming log line; for UI case it may ignore line content
      and probe external readiness.

    Returns True if a ready condition was met, False on timeout or if logs ended.
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
            # Stop if timeout
            if time.time() - start > timeout_sec:
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
