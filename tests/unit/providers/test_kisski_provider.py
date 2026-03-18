# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-FileCopyrightText: 2026 Andreas Knüpfer
# SPDX-License-Identifier: Apache-2.0

"""Tests for the KISSKI provider using the unified OpenCode base."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from terok.lib.providers.kisski_provider import KISSKIProvider
from tests.test_utils import make_mock_http_response

KISSKI_BASE_URL = "https://chat-ai.academiccloud.de/v1"
TEST_API_KEY = "test-api-key"


def build_update(
    provider: KISSKIProvider,
    *,
    base_url: str = KISSKI_BASE_URL,
    api_key: str = TEST_API_KEY,
    model: str = "devstral-2-123b-instruct-2512",
    models: list[str] | None = None,
) -> dict:
    """Create a KISSKI config fragment using the provider's real helper."""
    return provider._build_provider_update(base_url, api_key, model, models or [model])


@pytest.fixture
def kisski_provider():
    """Create a KISSKIProvider instance for testing."""
    return KISSKIProvider()


def test_provider_properties(kisski_provider: KISSKIProvider) -> None:
    """KISSKI provider has the expected properties."""
    assert kisski_provider.provider_name == "kisski"
    assert kisski_provider.display_name == "KISSKI"
    assert kisski_provider.default_base_url == KISSKI_BASE_URL
    assert kisski_provider.preferred_model == "devstral-2-123b-instruct-2512"
    assert kisski_provider.fallback_model == "mistral-large-3-675b-instruct-2512"
    assert kisski_provider.env_var_name == "KISSKI_API_KEY"
    assert kisski_provider.config_dir_name == ".kisski"
    assert kisski_provider.provider_config_key == "kisski"
    assert kisski_provider.provider_display_name == "KISSKI"


def test_config_paths(kisski_provider: KISSKIProvider) -> None:
    """KISSKI provider uses correct configuration paths."""
    home = Path.home()

    config_dir = kisski_provider._config_dir()
    assert config_dir == home / ".kisski"

    config_path = kisski_provider._config_path()
    assert config_path == home / ".kisski" / "config.json"

    opencode_config_path = kisski_provider._opencode_config_path()
    assert opencode_config_path == home / ".kisski" / "opencode" / "opencode.json"


def test_opencode_config_path_under_kisski_dir(kisski_provider: KISSKIProvider) -> None:
    """KISSKI uses its own OpenCode config directory under ``~/.kisski``."""
    config_path = kisski_provider._opencode_config_path()
    home = Path.home()
    assert config_path.resolve().is_relative_to((home / ".kisski").resolve())
    assert config_path.name == "opencode.json"
    assert config_path != home / ".config" / "opencode" / "opencode.json"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(
            {
                "data": [
                    {"id": "model-1", "object": "model"},
                    {"id": "model-2", "object": "model"},
                    {"id": "model-3", "object": "model"},
                ]
            },
            ["model-1", "model-2", "model-3"],
            id="data-array",
        ),
        pytest.param(
            {"models": [{"id": "custom-model-1"}, {"id": "custom-model-2"}]},
            ["custom-model-1", "custom-model-2"],
            id="models-array",
        ),
        pytest.param(
            {
                "data": [
                    {"id": "zebra-model"},
                    {"id": "alpha-model"},
                    {"id": "zebra-model"},
                    {"id": "beta-model"},
                ]
            },
            ["alpha-model", "beta-model", "zebra-model"],
            id="deduplicates-and-sorts",
        ),
    ],
)
def test_fetch_models_success(
    kisski_provider: KISSKIProvider, payload: dict[str, object], expected: list[str]
) -> None:
    """Model fetching supports both response shapes and normalizes the returned IDs."""
    with patch(
        "terok.lib.providers.opencode_base.request.urlopen",
        return_value=make_mock_http_response(payload),
    ):
        assert kisski_provider._fetch_models(KISSKI_BASE_URL, TEST_API_KEY) == expected


def test_fetch_models_returns_none_on_error(kisski_provider: KISSKIProvider) -> None:
    """API failures return ``None`` instead of bubbling exceptions up."""
    from terok.lib.providers.opencode_base import error as base_error

    with patch(
        "terok.lib.providers.opencode_base.request.urlopen",
        side_effect=base_error.URLError("Connection failed"),
    ):
        assert kisski_provider._fetch_models(KISSKI_BASE_URL, TEST_API_KEY) is None


@pytest.mark.parametrize(
    ("model", "models"),
    [
        pytest.param("test-model", ["test-model", "other-model"], id="basic"),
        pytest.param(
            "devstral-2-123b-instruct-2512",
            ["devstral-2-123b-instruct-2512", "other-model"],
            id="json-structure",
        ),
    ],
)
def test_build_kisski_update(
    kisski_provider: KISSKIProvider, model: str, models: list[str]
) -> None:
    """The generated config fragment has the expected OpenCode provider structure."""
    config = build_update(
        kisski_provider,
        base_url=KISSKI_BASE_URL,
        api_key="test-api-key-456",
        model=model,
        models=models,
    )
    parsed = json.loads(json.dumps(config, indent=2))
    provider = parsed["provider"]["kisski"]

    assert parsed["$schema"] == "https://opencode.ai/config.json"
    assert parsed["model"] == f"kisski/{model}"
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["name"] == "KISSKI"
    assert provider["options"]["baseURL"] == KISSKI_BASE_URL
    assert provider["options"]["apiKey"] == "test-api-key-456"
    assert parsed["permission"]["*"] == "allow"
    for model_id in models:
        assert model_id in provider["models"]


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        pytest.param(
            {
                "provider": {
                    "kisski": {
                        "models": {
                            "model-a": {"name": "Model A"},
                            "model-b": {"name": "Model B"},
                        }
                    }
                }
            },
            {"model-a", "model-b"},
            id="configured-models",
        ),
        pytest.param(None, set(), id="none"),
        pytest.param({}, set(), id="missing-provider"),
        pytest.param({"provider": {}}, set(), id="empty-provider"),
    ],
)
def test_get_configured_models(
    kisski_provider: KISSKIProvider, config: dict | None, expected: set[str]
) -> None:
    """Configured-model extraction handles missing config and valid provider maps."""
    assert kisski_provider._get_configured_models(config) == expected


@pytest.mark.parametrize(
    ("schema", "should_warn"),
    [
        pytest.param("https://example.com/wrong.json", True, id="schema-mismatch"),
        pytest.param("https://opencode.ai/config.json", False, id="schema-match"),
    ],
)
def test_merge_schema_warning(
    kisski_provider: KISSKIProvider, schema: str, should_warn: bool
) -> None:
    """Schema mismatches print a warning and are overwritten to the expected value."""
    with patch("builtins.print") as mock_print:
        merged = kisski_provider._merge_provider_config(
            {"$schema": schema},
            build_update(kisski_provider, base_url="https://api.example.com/v1", api_key="key"),
        )

    assert mock_print.called is should_warn
    assert merged["$schema"] == "https://opencode.ai/config.json"
    if should_warn:
        assert "unexpected $schema" in mock_print.call_args.args[0]


def test_main_passes_opencode_config_env(kisski_provider: KISSKIProvider) -> None:
    """Running the wrapper passes ``OPENCODE_CONFIG`` to the spawned OpenCode process."""
    mock_response = make_mock_http_response({"data": [{"id": "devstral-2-123b-instruct-2512"}]})
    with tempfile.TemporaryDirectory() as td:
        config_path = Path(td) / "opencode" / "opencode.json"
        with (
            patch.object(kisski_provider, "_load_api_key", return_value="fake-key"),
            patch("terok.lib.providers.opencode_base.request.urlopen", return_value=mock_response),
            patch.object(kisski_provider, "_opencode_config_path", return_value=config_path),
            patch("terok.lib.providers.opencode_base.subprocess.call", return_value=0) as mock_call,
            patch("sys.argv", ["kisski"]),
        ):
            kisski_provider.main()

    env = mock_call.call_args.kwargs["env"]
    assert env["OPENCODE_CONFIG"] == str(config_path)


def test_main_preserves_instructions_on_update(kisski_provider: KISSKIProvider) -> None:
    """Updating config through ``main()`` preserves existing ``instructions`` entries."""
    mock_response = make_mock_http_response({"data": [{"id": "devstral-2-123b-instruct-2512"}]})

    with tempfile.TemporaryDirectory() as td:
        config_path = Path(td) / "opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(
                {
                    "instructions": ["/tmp/instructions.md"],
                    "provider": {
                        "kisski": {
                            "options": {"baseURL": "https://old/v1", "apiKey": "old"},
                            "models": {},
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        with (
            patch.object(kisski_provider, "_load_api_key", return_value="new-key"),
            patch("terok.lib.providers.opencode_base.request.urlopen", return_value=mock_response),
            patch.object(kisski_provider, "_opencode_config_path", return_value=config_path),
            patch("terok.lib.providers.opencode_base.subprocess.call", return_value=0),
            patch("sys.argv", ["kisski"]),
        ):
            kisski_provider.main()

        updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated["instructions"] == ["/tmp/instructions.md"]
    assert updated["provider"]["kisski"]["options"]["apiKey"] == "new-key"
