# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-FileCopyrightText: 2026 Andreas Knüpfer
# SPDX-License-Identifier: Apache-2.0

"""KISSKI provider implementation using the unified OpenCode base."""

from .opencode_base import OpenCodeProvider


class KISSKIProvider(OpenCodeProvider):
    """KISSKI provider for OpenCode."""

    @property
    def provider_name(self) -> str:
        return "kisski"

    @property
    def display_name(self) -> str:
        return "KISSKI"

    @property
    def default_base_url(self) -> str:
        return "https://chat-ai.academiccloud.de/v1"

    @property
    def preferred_model(self) -> str:
        return "devstral-2-123b-instruct-2512"

    @property
    def fallback_model(self) -> str:
        return "mistral-large-3-675b-instruct-2512"

    @property
    def env_var_name(self) -> str:
        return "KISSKI_API_KEY"

    @property
    def config_dir_name(self) -> str:
        return ".kisski"

    @property
    def provider_config_key(self) -> str:
        return "kisski"

    @property
    def provider_display_name(self) -> str:
        return "KISSKI"


def main() -> int:
    """Entry point for kisski command."""
    provider = KISSKIProvider()
    return provider.main()


if __name__ == "__main__":
    raise SystemExit(main())
