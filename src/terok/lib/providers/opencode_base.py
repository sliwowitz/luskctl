# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Base class for OpenCode-based AI providers (Blablador, KISSKI, etc.).

This module provides a unified abstraction for providers that use OpenCode
with different API backends, reducing code duplication while preserving
provider-specific configuration and behavior.
"""

import argparse
import json
import os
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib import error, request


class OpenCodeProvider(ABC):
    """Base class for OpenCode-based AI providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Short name of the provider (e.g., 'blablador', 'kisski')."""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name of the provider."""
        pass

    @property
    @abstractmethod
    def default_base_url(self) -> str:
        """Default API base URL."""
        pass

    @property
    @abstractmethod
    def preferred_model(self) -> str:
        """Preferred model ID."""
        pass

    @property
    @abstractmethod
    def fallback_model(self) -> str:
        """Fallback model ID if preferred is unavailable."""
        pass

    @property
    @abstractmethod
    def env_var_name(self) -> str:
        """Environment variable name for API key."""
        pass

    @property
    @abstractmethod
    def config_dir_name(self) -> str:
        """Configuration directory name (e.g., '.blablador', '.kisski')."""
        pass

    @property
    @abstractmethod
    def provider_config_key(self) -> str:
        """Key used in opencode.json provider configuration."""
        pass

    @property
    @abstractmethod
    def provider_display_name(self) -> str:
        """Provider display name in opencode.json."""
        pass

    def _config_dir(self) -> Path:
        """Return the provider-specific configuration directory."""
        return Path.home() / self.config_dir_name

    def _config_path(self) -> Path:
        """Return the path to the provider's config.json file."""
        return self._config_dir() / "config.json"

    def _load_api_key(self) -> str | None:
        """Load API key from environment or config file."""
        api_key = os.environ.get(self.env_var_name)
        if api_key:
            return api_key

        cfg_path = self._config_path()
        if not cfg_path.is_file():
            return None

        try:
            data = json.loads(cfg_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

        val = data.get("api_key")
        return val if isinstance(val, str) and val.strip() else None

    def _fetch_models(self, base_url: str, api_key: str) -> list[str] | None:
        """Fetch available models from the API. Returns None on failure."""
        url = base_url.rstrip("/") + "/models"
        req = request.Request(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )

        try:
            with request.urlopen(req, timeout=30) as resp:  # nosec B310
                payload = json.loads(resp.read().decode("utf-8"))
        except (error.HTTPError, error.URLError, json.JSONDecodeError):
            return None

        items: Iterable[object] = []
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                items = payload["data"]
            elif isinstance(payload.get("models"), list):
                items = payload["models"]

        models: list[str] = []
        for item in items:
            if isinstance(item, dict):
                model_id = item.get("id")
                if isinstance(model_id, str) and model_id:
                    models.append(model_id)

        return sorted(set(models)) if models else None

    def _build_provider_update(
        self,
        base_url: str,
        api_key: str,
        model: str,
        models: list[str] | None,
    ) -> dict[str, Any]:
        """Build the provider-specific config fragment for opencode.json."""
        model_map = {model: {"name": model}}
        if models:
            for mid in models:
                if isinstance(mid, str) and mid:
                    model_map.setdefault(mid, {"name": mid})

        return {
            "$schema": "https://opencode.ai/config.json",
            "model": f"{self.provider_name}/{model}",
            "provider": {
                self.provider_config_key: {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": self.provider_display_name,
                    "options": {
                        "baseURL": base_url,
                        "apiKey": api_key,
                    },
                    "models": model_map,
                }
            },
            "permission": {
                "*": "allow",
            },
        }

    def _merge_provider_config(self, existing: dict, update: dict) -> dict:
        """Merge provider update into existing opencode.json config."""
        merged = dict(existing)

        # Schema handling
        existing_schema = merged.get("$schema")
        expected_schema = update["$schema"]
        if existing_schema and existing_schema != expected_schema:
            print(
                f"Warning: opencode.json has unexpected $schema value "
                f"{existing_schema!r}, expected {expected_schema!r}. Overwriting."
            )
        merged["$schema"] = expected_schema

        # Provider deep-merge
        existing_providers = merged.get("provider")
        if not isinstance(existing_providers, dict):
            existing_providers = {}
        update_providers = update.get("provider", {})
        merged_providers = dict(existing_providers)
        merged_providers.update(update_providers)
        merged["provider"] = merged_providers

        # Model handling - only overwrite if unset or already provider-prefixed
        current_model = merged.get("model")
        if not current_model or (
            isinstance(current_model, str) and current_model.startswith(f"{self.provider_name}/")
        ):
            merged["model"] = update["model"]

        # Permission - only set if not already configured
        if "permission" not in merged:
            merged["permission"] = update["permission"]

        return merged

    def _opencode_config_path(self) -> Path:
        """Return the provider-specific OpenCode config path."""
        return self._config_dir() / "opencode" / "opencode.json"

    def _load_opencode_config(self) -> dict | None:
        """Load existing OpenCode config if present."""
        config_path = self._opencode_config_path()
        if not config_path.is_file():
            return None

        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _get_configured_models(self, config: dict | None) -> set[str]:
        """Extract model IDs from existing provider config."""
        if not config:
            return set()

        try:
            models = config.get("provider", {}).get(self.provider_config_key, {}).get("models", {})
            return set(models.keys()) if isinstance(models, dict) else set()
        except (AttributeError, TypeError):
            return set()

    def _get_configured_options(self, config: dict | None) -> dict:
        """Extract provider options from existing config."""
        if not config:
            return {}

        try:
            options = (
                config.get("provider", {}).get(self.provider_config_key, {}).get("options", {})
            )
            return options if isinstance(options, dict) else {}
        except (AttributeError, TypeError):
            return {}

    def _write_opencode_config(self, config: dict) -> Path:
        """Write config to OpenCode's location via atomic replace."""
        import tempfile

        config_path = self._opencode_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = None

        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=config_path.parent, suffix=".tmp", delete=False
            ) as f:
                tmp_path = f.name
                f.write(json.dumps(config, indent=2) + "\n")
            os.replace(tmp_path, config_path)
        except BaseException:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

        return config_path

    def main(self) -> int:
        """Main entry point for the provider launcher."""
        parser = argparse.ArgumentParser(
            prog=self.provider_name,
            description=f"Run OpenCode against {self.display_name} with full permissions.",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=(
                "Examples:\n"
                f"  {self.provider_name}                # launch with preferred model\n"
                f"  {self.provider_name} --list-models  # list available models\n"
                f"  {self.provider_name} -- --help      # pass flags to opencode\n"
            ),
        )
        parser.add_argument(
            "--list-models", action="store_true", help="List available models and exit"
        )
        parser.add_argument(
            "--base-url",
            default=None,
            help=f"Override API base URL (default: {self.default_base_url})",
        )

        args, opencode_args = parser.parse_known_args()

        # Load and validate API key
        api_key = self._load_api_key()
        if not api_key:
            raise SystemExit(
                f"Missing {self.env_var_name}. Set it in the environment or write "
                f'{{{"api_key": "..."}}} to {self._config_path()}.'
            )

        # Determine base URL
        base_url = (
            args.base_url
            or os.environ.get(f"{self.env_var_name.replace('API_KEY', 'BASE_URL')}")
            or self.default_base_url
        )
        base_url = base_url.rstrip("/")

        # Fetch models from API
        fetched_models = self._fetch_models(base_url, api_key)

        if args.list_models:
            if fetched_models:
                for model in fetched_models:
                    print(model)
            else:
                raise SystemExit(f"Failed to fetch models from {self.display_name} API")
            return 0

        # Load existing config
        existing_config = self._load_opencode_config()
        configured_models = self._get_configured_models(existing_config)

        # Determine which model to use
        model = self.preferred_model
        if fetched_models and self.preferred_model not in fetched_models:
            print(
                f"Warning: Preferred model '{self.preferred_model}' is no longer available.\n"
                f"Falling back to '{self.fallback_model}'.\n"
                "Check for new upstream versions of terok to update the default model."
            )
            model = self.fallback_model

        # Update config if needed
        stored_options = self._get_configured_options(existing_config)
        options_changed = (
            stored_options.get("baseURL") != base_url or stored_options.get("apiKey") != api_key
        )

        if fetched_models:
            fetched_set = set(fetched_models)
            needs_update = fetched_set != configured_models or options_changed
            if needs_update:
                new_models = fetched_set - configured_models
                if new_models:
                    print(f"New models available: {', '.join(sorted(new_models))}")
                update = self._build_provider_update(base_url, api_key, model, fetched_models)
                merged = self._merge_provider_config(existing_config or {}, update)
                self._write_opencode_config(merged)
        elif options_changed or not configured_models:
            # Fetch failed: preserve known models if available
            fallback_models = sorted(configured_models) if configured_models else [model]
            update = self._build_provider_update(base_url, api_key, model, fallback_models)
            merged = self._merge_provider_config(existing_config or {}, update)
            self._write_opencode_config(merged)

        # Launch OpenCode
        cmd = ["opencode"] + opencode_args
        env = {**os.environ, "OPENCODE_CONFIG": str(self._opencode_config_path())}

        try:
            return subprocess.call(cmd, env=env)
        except FileNotFoundError:
            raise SystemExit("opencode not found. Rebuild the L1 CLI image to install it.")


def create_provider_launcher(provider_class: type[OpenCodeProvider]) -> None:
    """Create a standalone launcher script for the given provider."""
    if __name__ == "__main__":
        provider = provider_class()
        raise SystemExit(provider.main())
