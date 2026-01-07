from __future__ import annotations

import shutil
import subprocess
from importlib import resources
from pathlib import Path

import yaml  # pip install pyyaml

from .config import build_root
from .projects import _effective_ssh_key_name, load_project


# ---------- Dockerfile gen & build ----------

def _ensure_dir(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)


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
