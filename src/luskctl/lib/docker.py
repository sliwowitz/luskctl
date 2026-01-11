import hashlib
import shutil
import subprocess
from functools import lru_cache
from importlib import resources
from pathlib import Path

import yaml  # pip install pyyaml

from .config import build_root
from .images import (
    agent_cli_image,
    agent_ui_image,
    base_dev_image,
    project_cli_image,
    project_dev_image,
    project_web_image,
)
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

    Single source of truth: luskctl/resources/scripts bundled in the wheel.
    """
    pkg_rel = "resources/scripts"
    # Replace destination directory atomically-ish
    if dest.exists():
        shutil.rmtree(dest)
    _copy_package_tree("luskctl", pkg_rel, dest)


def _load_docker_config(project_root: Path) -> dict:
    try:
        cfg = yaml.safe_load((project_root / "project.yml").read_text()) or {}
        return cfg.get("docker", {}) or {}
    except Exception:
        return {}


def _hash_traversable_tree(root) -> str:
    hasher = hashlib.sha256()

    def _walk(node, prefix: str) -> None:
        for child in sorted(node.iterdir(), key=lambda item: item.name):
            rel = f"{prefix}{child.name}"
            if child.is_dir():
                _walk(child, f"{rel}/")
            else:
                hasher.update(rel.encode("utf-8"))
                hasher.update(b"\0")
                hasher.update(child.read_bytes())
                hasher.update(b"\0")

    _walk(root, "")
    return hasher.hexdigest()


@lru_cache(maxsize=1)
def _scripts_hash() -> str:
    scripts_root = resources.files("luskctl") / "resources" / "scripts"
    return _hash_traversable_tree(scripts_root)


def _render_dockerfiles(project) -> dict[str, str]:
    # Load templates from package resources (luskctl/resources/templates). Use
    # importlib.resources Traversable API so it works from wheels/zip too.
    tmpl_pkg = resources.files("luskctl") / "resources" / "templates"
    templates = {
        "L0.Dockerfile": (tmpl_pkg / "l0.dev.Dockerfile.template").read_text(),
        "L1.cli.Dockerfile": (tmpl_pkg / "l1.agent-cli.Dockerfile.template").read_text(),
        "L1.ui.Dockerfile": (tmpl_pkg / "l1.agent-ui.Dockerfile.template").read_text(),
        "L2.Dockerfile": (tmpl_pkg / "l2.project.Dockerfile.template").read_text(),
    }

    # Read additional docker-related settings directly from the project.yml
    docker_cfg = _load_docker_config(project.root)

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
        # For gatekeeping projects, default CODE_REPO to the git-gate mount path.
        # For online projects, default to the real upstream URL.
        # These defaults can be overridden at runtime via -e flags.
        "CODE_REPO_DEFAULT": (
            "file:///git-gate/gate.git"
            if project.security_class == "gatekeeping"
            else (project.upstream_url or "")
        ),
        "USER_SNIPPET": user_snippet,
    }

    rendered = {}
    for name, content in templates.items():
        for k, v in variables.items():
            content = content.replace(f"{{{{{k}}}}}", str(v))
        rendered[name] = content
    return rendered


def build_context_hash(project_id: str) -> str:
    project = load_project(project_id)
    rendered = _render_dockerfiles(project)
    docker_cfg = _load_docker_config(project.root)
    base_image = str(docker_cfg.get("base_image", "ubuntu:24.04"))

    hasher = hashlib.sha256()
    hasher.update(f"base_image={base_image}".encode())
    hasher.update(b"\0")
    for name in sorted(rendered):
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(rendered[name].encode("utf-8"))
        hasher.update(b"\0")
    hasher.update(_scripts_hash().encode("utf-8"))
    return hasher.hexdigest()


def dockerfiles_match_templates(project_id: str) -> bool:
    project = load_project(project_id)
    out_dir = build_root() / project.id
    rendered = _render_dockerfiles(project)
    for name, expected in rendered.items():
        path = out_dir / name
        if not path.is_file():
            return False
        if path.read_text() != expected:
            return False
    return True


def generate_dockerfiles(project_id: str) -> None:
    project = load_project(project_id)
    out_dir = build_root() / project.id
    _ensure_dir(out_dir)

    rendered = _render_dockerfiles(project)
    for name, content in rendered.items():
        (out_dir / name).write_text(content)

    # Stage auxiliary scripts into build context so Dockerfile COPY works.
    try:
        _stage_scripts_into(out_dir / "scripts")
    except Exception:
        # Non-fatal: some templates may not need scripts
        pass

    print(f"Generated Dockerfiles in {out_dir}")


def build_images(project_id: str, include_dev: bool = False) -> None:
    project = load_project(project_id)
    docker_cfg = _load_docker_config(project.root)
    stage_dir = build_root() / project.id
    context_hash = build_context_hash(project_id)

    l0 = stage_dir / "L0.Dockerfile"
    l1_cli = stage_dir / "L1.cli.Dockerfile"
    l1_ui = stage_dir / "L1.ui.Dockerfile"
    l2 = stage_dir / "L2.Dockerfile"

    if not l0.is_file() or not l1_cli.is_file() or not l1_ui.is_file() or not l2.is_file():
        raise SystemExit("Dockerfiles are missing. Run 'luskctl generate <project>' first.")

    # Build commands (using podman). Real implementation would pass context and tags.
    # Build with the project-specific build directory as context so COPY scripts/ works
    context_dir = str(stage_dir)

    base_image = str(docker_cfg.get("base_image", "ubuntu:24.04"))
    l0_image = base_dev_image(base_image)
    l1_cli_image = agent_cli_image(base_image)
    l1_ui_image = agent_ui_image(base_image)
    l2_cli_image = project_cli_image(project.id)
    l2_ui_image = project_web_image(project.id)
    l2_dev_image = project_dev_image(project.id)

    cmds = [
        [
            "podman",
            "build",
            "-f",
            str(l0),
            "--build-arg",
            f"BASE_IMAGE={base_image}",
            "-t",
            l0_image,
            context_dir,
        ],
        [
            "podman",
            "build",
            "-f",
            str(l1_cli),
            "--build-arg",
            f"BASE_IMAGE={l0_image}",
            "-t",
            l1_cli_image,
            context_dir,
        ],
        [
            "podman",
            "build",
            "-f",
            str(l1_ui),
            "--build-arg",
            f"BASE_IMAGE={l0_image}",
            "-t",
            l1_ui_image,
            context_dir,
        ],
        [
            "podman",
            "build",
            "-f",
            str(l2),
            "--build-arg",
            f"BASE_IMAGE={l1_cli_image}",
            "--label",
            f"luskctl.build_context_hash={context_hash}",
            "-t",
            l2_cli_image,
            context_dir,
        ],
        [
            "podman",
            "build",
            "-f",
            str(l2),
            "--build-arg",
            f"BASE_IMAGE={l1_ui_image}",
            "--label",
            f"luskctl.build_context_hash={context_hash}",
            "-t",
            l2_ui_image,
            context_dir,
        ],
    ]
    if include_dev:
        cmds.append(
            [
                "podman",
                "build",
                "-f",
                str(l2),
                "--build-arg",
                f"BASE_IMAGE={l0_image}",
                "--label",
                f"luskctl.build_context_hash={context_hash}",
                "-t",
                l2_dev_image,
                context_dir,
            ]
        )
    for cmd in cmds:
        print("$", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True)
        except FileNotFoundError:
            raise SystemExit("podman not found; please install podman")
        except subprocess.CalledProcessError as e:
            raise SystemExit(f"Build failed: {e}")
