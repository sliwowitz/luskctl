from __future__ import annotations


BASE_DEV_IMAGE = "codexctl-l0:latest"
AGENT_CLI_IMAGE = "codexctl-l1-cli:latest"
AGENT_UI_IMAGE = "codexctl-l1-ui:latest"


def base_dev_image() -> str:
    return BASE_DEV_IMAGE


def agent_cli_image() -> str:
    return AGENT_CLI_IMAGE


def agent_ui_image() -> str:
    return AGENT_UI_IMAGE


def project_cli_image(project_id: str) -> str:
    return f"{project_id}:l2-cli"


def project_ui_image(project_id: str) -> str:
    return f"{project_id}:l2-ui"


def project_dev_image(project_id: str) -> str:
    return f"{project_id}:l2-dev"
