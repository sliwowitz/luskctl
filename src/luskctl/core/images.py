import hashlib
import re


def _base_tag(base_image: str) -> str:
    raw = (base_image or "").strip()
    if not raw:
        raw = "ubuntu-24.04"
    tag = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-.").lower()
    if not tag:
        tag = "ubuntu-24.04"
    if len(tag) > 120:
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
        tag = f"{tag[:111]}-{digest}"
    return tag


def base_dev_image(base_image: str) -> str:
    return f"luskctl-l0:{_base_tag(base_image)}"


def agent_cli_image(base_image: str) -> str:
    return f"luskctl-l1-cli:{_base_tag(base_image)}"


def agent_ui_image(base_image: str) -> str:
    return f"luskctl-l1-ui:{_base_tag(base_image)}"


def project_cli_image(project_id: str) -> str:
    return f"{project_id}:l2-cli"


def project_web_image(project_id: str) -> str:
    return f"{project_id}:l2-web"


def project_dev_image(project_id: str) -> str:
    return f"{project_id}:l2-dev"
