# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest.mock
from pathlib import Path

from terok.lib.wizards.new_project import (
    TEMPLATES,
    _validate_project_id,
    collect_wizard_inputs,
    generate_config,
    run_wizard,
)


class TestValidateProjectId:
    """Tests for _validate_project_id()."""

    def test_valid_simple(self) -> None:
        assert _validate_project_id("myproject") is None

    def test_valid_with_hyphens(self) -> None:
        assert _validate_project_id("my-project") is None

    def test_valid_with_underscores(self) -> None:
        assert _validate_project_id("my_project") is None

    def test_valid_with_digits(self) -> None:
        assert _validate_project_id("proj123") is None

    def test_uppercase_rejected(self) -> None:
        assert _validate_project_id("My-Project_2") is not None

    def test_valid_mixed_lowercase(self) -> None:
        assert _validate_project_id("my-project_2") is None

    def test_empty_string(self) -> None:
        assert _validate_project_id("") is not None

    def test_spaces(self) -> None:
        assert _validate_project_id("my project") is not None

    def test_special_chars(self) -> None:
        assert _validate_project_id("my@project") is not None

    def test_starts_with_hyphen(self) -> None:
        assert _validate_project_id("-myproject") is not None

    def test_starts_with_underscore(self) -> None:
        assert _validate_project_id("_myproject") is not None


class TestCollectWizardInputs:
    """Tests for collect_wizard_inputs()."""

    @unittest.mock.patch(
        "builtins.input", side_effect=["1", "myproj", "https://example.com/r.git", "main", "n"]
    )
    def test_collects_all_values(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        assert result is not None
        assert result["template_index"] == 0
        assert result["project_id"] == "myproj"
        assert result["upstream_url"] == "https://example.com/r.git"
        assert result["default_branch"] == "main"
        assert result["user_snippet"] == ""

    @unittest.mock.patch("builtins.input", side_effect=["3", "gkproj", "git@host:r.git", "", "n"])
    def test_gatekeeping_template_selection(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        assert result is not None
        assert result["template_index"] == 2

    @unittest.mock.patch(
        "builtins.input", side_effect=["2", "proj", "https://x.com/r.git", "", "n"]
    )
    def test_default_branch_defaults_to_empty(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        assert result is not None
        assert result["default_branch"] == ""

    @unittest.mock.patch(
        "builtins.input", side_effect=["2", "proj", "https://x.com/r.git", "dev", "n"]
    )
    def test_custom_branch(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        assert result["default_branch"] == "dev"

    @unittest.mock.patch("builtins.input", side_effect=["invalid"])
    def test_invalid_template_returns_none(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        assert result is None

    @unittest.mock.patch("builtins.input", side_effect=["0"])
    def test_out_of_range_template_returns_none(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        assert result is None

    @unittest.mock.patch("builtins.input", side_effect=["5"])
    def test_template_above_range_returns_none(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        assert result is None

    @unittest.mock.patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_ctrl_c_returns_none(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        assert result is None

    @unittest.mock.patch("builtins.input", side_effect=EOFError)
    def test_eof_returns_none(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        assert result is None

    @unittest.mock.patch(
        "builtins.input",
        side_effect=["1", "MyProject", "https://x.com/r.git", "main", "n"],
    )
    @unittest.mock.patch("builtins.print")
    def test_uppercase_auto_lowercased(
        self, mock_print: unittest.mock.Mock, _input: unittest.mock.Mock
    ) -> None:
        result = collect_wizard_inputs()
        assert result is not None
        assert result["project_id"] == "myproject"
        printed = [" ".join(str(a) for a in c.args) for c in mock_print.call_args_list]
        assert any("lowercased to 'myproject'" in line for line in printed)

    @unittest.mock.patch(
        "builtins.input",
        side_effect=["1", "bad project", "good-id", "https://x.com/r.git", "main", "n"],
    )
    def test_retries_on_invalid_project_id(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        assert result is not None
        assert result["project_id"] == "good-id"

    @unittest.mock.patch(
        "builtins.input",
        side_effect=["1", "proj", "", "https://x.com/r.git", "main", "n"],
    )
    def test_retries_on_empty_upstream_url(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        assert result is not None
        assert result["upstream_url"] == "https://x.com/r.git"


class TestGenerateConfig:
    """Tests for generate_config()."""

    def test_generates_project_yml(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with unittest.mock.patch(
                "terok.lib.wizards.new_project.user_projects_root", return_value=Path(td)
            ):
                values = {
                    "template_index": 0,
                    "project_id": "test-proj",
                    "upstream_url": "https://github.com/user/repo.git",
                    "default_branch": "main",
                    "user_snippet": "",
                }
                result = generate_config(values)

                assert result.exists()
                assert result.name == "project.yml"
                content = result.read_text(encoding="utf-8")
                assert 'id: "test-proj"' in content
                assert "https://github.com/user/repo.git" in content
                assert 'default_branch: "main"' in content
                assert 'security_class: "online"' in content

    def test_generates_gatekeeping_template(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with unittest.mock.patch(
                "terok.lib.wizards.new_project.user_projects_root", return_value=Path(td)
            ):
                values = {
                    "template_index": 2,
                    "project_id": "gk-proj",
                    "upstream_url": "git@github.com:user/repo.git",
                    "default_branch": "dev",
                    "user_snippet": "RUN apt-get update",
                }
                result = generate_config(values)

                content = result.read_text(encoding="utf-8")
                assert 'security_class: "gatekeeping"' in content
                assert 'default_branch: "dev"' in content
                assert "RUN apt-get update" in content
                assert "gatekeeping:" in content

    def test_creates_project_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with unittest.mock.patch(
                "terok.lib.wizards.new_project.user_projects_root", return_value=Path(td)
            ):
                values = {
                    "template_index": 0,
                    "project_id": "new-proj",
                    "upstream_url": "https://x.com/r.git",
                    "default_branch": "main",
                    "user_snippet": "",
                }
                result = generate_config(values)
                assert result.parent.is_dir()
                assert result.parent.name == "new-proj"

    def test_nvidia_template_includes_gpus(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with unittest.mock.patch(
                "terok.lib.wizards.new_project.user_projects_root", return_value=Path(td)
            ):
                values = {
                    "template_index": 1,
                    "project_id": "gpu-proj",
                    "upstream_url": "https://x.com/r.git",
                    "default_branch": "main",
                    "user_snippet": "",
                }
                result = generate_config(values)
                content = result.read_text(encoding="utf-8")
                assert "gpus: all" in content
                assert "nvcr.io/nvidia/" in content

    def test_all_placeholders_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with unittest.mock.patch(
                "terok.lib.wizards.new_project.user_projects_root", return_value=Path(td)
            ):
                for idx in range(len(TEMPLATES)):
                    values = {
                        "template_index": idx,
                        "project_id": f"proj{idx}",
                        "upstream_url": "https://x.com/r.git",
                        "default_branch": "main",
                        "user_snippet": "RUN echo hi",
                    }
                    result = generate_config(values)
                    content = result.read_text(encoding="utf-8")
                    assert "{{PROJECT_ID}}" not in content
                    assert "{{UPSTREAM_URL}}" not in content
                    assert "{{DEFAULT_BRANCH}}" not in content
                    assert "{{USER_SNIPPET}}" not in content


class TestRunWizard:
    """Tests for run_wizard() orchestration."""

    @unittest.mock.patch("terok.lib.wizards.new_project.open_in_editor", return_value=True)
    @unittest.mock.patch("terok.lib.wizards.new_project.generate_config")
    @unittest.mock.patch("terok.lib.wizards.new_project.collect_wizard_inputs")
    def test_run_wizard_with_edit_and_init(
        self,
        mock_collect: unittest.mock.Mock,
        mock_generate: unittest.mock.Mock,
        mock_editor: unittest.mock.Mock,
    ) -> None:
        mock_collect.return_value = {
            "template_index": 0,
            "project_id": "proj1",
            "upstream_url": "https://x.com/r.git",
            "default_branch": "main",
            "user_snippet": "",
        }
        mock_generate.return_value = Path("/tmp/proj1/project.yml")
        mock_init = unittest.mock.Mock()

        with unittest.mock.patch("builtins.input", side_effect=["y", "y"]):
            result = run_wizard(init_fn=mock_init)

        assert result == Path("/tmp/proj1/project.yml")
        mock_editor.assert_called_once()
        mock_init.assert_called_once_with("proj1")

    @unittest.mock.patch("terok.lib.wizards.new_project.generate_config")
    @unittest.mock.patch("terok.lib.wizards.new_project.collect_wizard_inputs")
    def test_run_wizard_skip_edit_and_init(
        self,
        mock_collect: unittest.mock.Mock,
        mock_generate: unittest.mock.Mock,
    ) -> None:
        mock_collect.return_value = {
            "template_index": 0,
            "project_id": "proj2",
            "upstream_url": "https://x.com/r.git",
            "default_branch": "main",
            "user_snippet": "",
        }
        mock_generate.return_value = Path("/tmp/proj2/project.yml")
        mock_init = unittest.mock.Mock()

        with unittest.mock.patch("builtins.input", side_effect=["n", "n"]):
            result = run_wizard(init_fn=mock_init)

        assert result == Path("/tmp/proj2/project.yml")
        mock_init.assert_not_called()

    @unittest.mock.patch("terok.lib.wizards.new_project.collect_wizard_inputs", return_value=None)
    def test_run_wizard_cancellation_returns_none(self, _collect: unittest.mock.Mock) -> None:
        result = run_wizard()
        assert result is None

    @unittest.mock.patch("terok.lib.wizards.new_project.generate_config")
    @unittest.mock.patch("terok.lib.wizards.new_project.collect_wizard_inputs")
    def test_run_wizard_no_init_fn(
        self,
        mock_collect: unittest.mock.Mock,
        mock_generate: unittest.mock.Mock,
    ) -> None:
        mock_collect.return_value = {
            "template_index": 0,
            "project_id": "proj3",
            "upstream_url": "https://x.com/r.git",
            "default_branch": "main",
            "user_snippet": "",
        }
        mock_generate.return_value = Path("/tmp/proj3/project.yml")

        with unittest.mock.patch("builtins.input", side_effect=["n"]):
            result = run_wizard()

        assert result is not None

    @unittest.mock.patch("terok.lib.wizards.new_project.generate_config")
    @unittest.mock.patch("terok.lib.wizards.new_project.collect_wizard_inputs")
    def test_run_wizard_ctrl_c_after_generate(
        self,
        mock_collect: unittest.mock.Mock,
        mock_generate: unittest.mock.Mock,
    ) -> None:
        mock_collect.return_value = {
            "template_index": 0,
            "project_id": "proj4",
            "upstream_url": "https://x.com/r.git",
            "default_branch": "main",
            "user_snippet": "",
        }
        mock_generate.return_value = Path("/tmp/proj4/project.yml")

        with unittest.mock.patch("builtins.input", side_effect=KeyboardInterrupt):
            result = run_wizard()

        # Config was generated, so path is returned even if post-steps cancelled
        assert result is not None
