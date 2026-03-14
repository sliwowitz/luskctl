# SPDX-FileCopyrightText: 2026 Jiri Vyskocil
# SPDX-License-Identifier: Apache-2.0

"""Tests for task name functionality: sanitize, generate, rename, and YAML persistence."""

import re
import unittest.mock
from contextlib import redirect_stdout
from io import StringIO

import pytest
import yaml

from terok.lib.containers.tasks import (
    TASK_NAME_MAX_LEN,
    _default_categories_for_project,
    _resolve_name_categories,
    generate_task_name,
    get_tasks,
    sanitize_task_name,
    task_new,
    task_rename,
    validate_task_name,
)
from test_utils import project_env


class TestSanitizeTaskName:
    """Tests for sanitize_task_name()."""

    def test_none_returns_none(self) -> None:
        """None input returns None."""
        assert sanitize_task_name(None) is None

    def test_empty_returns_none(self) -> None:
        """Empty string returns None."""
        assert sanitize_task_name("") is None

    def test_whitespace_only_returns_none(self) -> None:
        """Whitespace-only string returns None."""
        assert sanitize_task_name("   ") is None

    def test_spaces_replaced_with_hyphens(self) -> None:
        """Spaces are replaced with hyphens."""
        assert sanitize_task_name("fix auth bug") == "fix-auth-bug"

    def test_underscores_preserved(self) -> None:
        """Underscores are kept as valid characters."""
        assert sanitize_task_name("fix_auth_bug") == "fix_auth_bug"

    def test_special_chars_stripped(self) -> None:
        """Non-alphanumeric characters (except hyphens and underscores) are stripped."""
        assert sanitize_task_name("fix@auth#bug!") == "fixauthbug"

    def test_uppercase_lowered(self) -> None:
        """Input is lowercased."""
        assert sanitize_task_name("Fix-Auth-Bug") == "fix-auth-bug"

    def test_consecutive_hyphens_collapsed(self) -> None:
        """Multiple consecutive hyphens collapse to one."""
        assert sanitize_task_name("fix---auth---bug") == "fix-auth-bug"

    def test_trailing_hyphens_stripped(self) -> None:
        """Trailing hyphens are stripped; leading hyphens are preserved."""
        assert sanitize_task_name("fix-bug-") == "fix-bug"
        assert sanitize_task_name("-fix-bug") == "-fix-bug"

    def test_truncation(self) -> None:
        """Names exceeding TASK_NAME_MAX_LEN are truncated."""
        long_name = "a" * 100
        result = sanitize_task_name(long_name)
        assert len(result) == TASK_NAME_MAX_LEN

    def test_mixed_transform(self) -> None:
        """Complex input with mixed issues sanitizes correctly."""
        assert sanitize_task_name("  Fix__Auth  Bug!! ") == "fix__auth-bug"

    def test_only_special_chars_returns_none(self) -> None:
        """Input with only special characters returns None."""
        assert sanitize_task_name("@#$%^&") is None

    def test_numeric_name(self) -> None:
        """Numeric-only names are allowed."""
        assert sanitize_task_name("42") == "42"


class TestValidateTaskName:
    """Tests for validate_task_name()."""

    def test_valid_name_returns_none(self) -> None:
        """A normal slug name passes validation."""
        assert validate_task_name("fix-auth-bug") is None

    def test_leading_hyphen_rejected(self) -> None:
        """A name starting with a hyphen is rejected."""
        err = validate_task_name("-fix-bug")
        assert err is not None
        assert "hyphen" in err

    def test_underscored_name_valid(self) -> None:
        """A name with underscores passes validation."""
        assert validate_task_name("fix_auth_bug") is None

    def test_numeric_name_valid(self) -> None:
        """A purely numeric name passes validation."""
        assert validate_task_name("42") is None


class TestGenerateTaskName:
    """Tests for generate_task_name()."""

    def test_returns_non_empty(self) -> None:
        """Generated name is a non-empty string."""
        name = generate_task_name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_matches_slug_pattern(self) -> None:
        """Generated name matches adjective-noun slug pattern."""
        name = generate_task_name()
        assert re.search(r"^[a-z]+-[a-z0-9]+$", name)

    def test_uses_hyphen_separator(self) -> None:
        """Generated name uses hyphen as separator."""
        name = generate_task_name()
        assert "-" in name


class TestTaskNewWithName:
    """Tests for task_new() with the name parameter."""

    def test_task_new_with_explicit_name(self) -> None:
        """task_new with explicit name stores sanitized name in YAML."""
        project_id = "proj_name1"
        with project_env(
            f"project:\n  id: {project_id}\n",
            project_id=project_id,
        ) as ctx:
            task_new(project_id, name="Fix Auth Bug")

            meta_path = ctx.state_dir / "projects" / project_id / "tasks" / "1.yml"
            meta = yaml.safe_load(meta_path.read_text())
            assert meta["name"] == "fix-auth-bug"

    def test_task_new_default_name(self) -> None:
        """task_new without explicit name generates an auto name (not None)."""
        project_id = "proj_name2"
        with project_env(
            f"project:\n  id: {project_id}\n",
            project_id=project_id,
        ):
            task_new(project_id)

            tasks = get_tasks(project_id)
            assert len(tasks) == 1
            assert tasks[0].name is not None
            assert re.search(r"^[a-z]+-[a-z]+$", tasks[0].name)

    def test_task_new_invalid_name_raises(self) -> None:
        """task_new with all-special-char name raises SystemExit and leaves no artifacts."""
        project_id = "proj_name_inv"
        with project_env(
            f"project:\n  id: {project_id}\n",
            project_id=project_id,
        ) as ctx:
            with pytest.raises(SystemExit):
                task_new(project_id, name="@#$")
            meta_path = ctx.state_dir / "projects" / project_id / "tasks" / "1.yml"
            assert not meta_path.exists()

    def test_task_new_leading_hyphen_raises(self) -> None:
        """task_new with a leading hyphen raises SystemExit and leaves no artifacts."""
        project_id = "proj_name_hyp"
        with project_env(
            f"project:\n  id: {project_id}\n",
            project_id=project_id,
        ) as ctx:
            with pytest.raises(SystemExit):
                task_new(project_id, name="-my-task")
            meta_path = ctx.state_dir / "projects" / project_id / "tasks" / "1.yml"
            assert not meta_path.exists()

    def test_task_new_prints_name(self) -> None:
        """task_new output includes the task name."""
        project_id = "proj_name3"
        with project_env(
            f"project:\n  id: {project_id}\n",
            project_id=project_id,
        ):
            buf = StringIO()
            with redirect_stdout(buf):
                task_new(project_id, name="my-task")
            output = buf.getvalue()
            assert "my-task" in output


class TestTaskRename:
    """Tests for task_rename()."""

    def test_rename_task(self) -> None:
        """task_rename updates the name in YAML."""
        project_id = "proj_rename1"
        with project_env(
            f"project:\n  id: {project_id}\n",
            project_id=project_id,
        ) as ctx:
            task_new(project_id, name="old-name")
            task_rename(project_id, "1", "new-name")

            meta_path = ctx.state_dir / "projects" / project_id / "tasks" / "1.yml"
            meta = yaml.safe_load(meta_path.read_text())
            assert meta["name"] == "new-name"

    def test_rename_unknown_task_raises(self) -> None:
        """task_rename on unknown task raises SystemExit."""
        project_id = "proj_rename2"
        with project_env(
            f"project:\n  id: {project_id}\n",
            project_id=project_id,
        ):
            with pytest.raises(SystemExit):
                task_rename(project_id, "999", "new-name")

    def test_rename_invalid_name_raises(self) -> None:
        """task_rename with an empty/invalid name raises SystemExit."""
        project_id = "proj_rename3"
        with project_env(
            f"project:\n  id: {project_id}\n",
            project_id=project_id,
        ):
            task_new(project_id)
            with pytest.raises(SystemExit):
                task_rename(project_id, "1", "@#$%")

    def test_rename_leading_hyphen_raises(self) -> None:
        """task_rename with a leading-hyphen name raises SystemExit."""
        project_id = "proj_rename5"
        with project_env(
            f"project:\n  id: {project_id}\n",
            project_id=project_id,
        ):
            task_new(project_id)
            with pytest.raises(SystemExit):
                task_rename(project_id, "1", "-badname")

    def test_rename_sanitizes(self) -> None:
        """task_rename sanitizes the new name."""
        project_id = "proj_rename4"
        with project_env(
            f"project:\n  id: {project_id}\n",
            project_id=project_id,
        ) as ctx:
            task_new(project_id)
            task_rename(project_id, "1", "My New Name")

            meta_path = ctx.state_dir / "projects" / project_id / "tasks" / "1.yml"
            meta = yaml.safe_load(meta_path.read_text())
            assert meta["name"] == "my-new-name"


class TestGetTasksLoadsName:
    """Tests for name field in get_tasks()."""

    def test_get_tasks_loads_name(self) -> None:
        """get_tasks() populates TaskMeta.name from YAML."""
        project_id = "proj_load_name"
        with project_env(
            f"project:\n  id: {project_id}\n",
            project_id=project_id,
        ):
            task_new(project_id, name="test-task")

            tasks = get_tasks(project_id)
            assert len(tasks) == 1
            assert tasks[0].name == "test-task"


class TestDefaultCategoriesForProject:
    """Tests for _default_categories_for_project()."""

    def test_returns_three_categories(self) -> None:
        """Hash-based selection returns exactly 3 categories."""
        cats = _default_categories_for_project("myproject")
        assert len(cats) == 3

    def test_categories_are_valid(self) -> None:
        """All returned categories exist in the namer library."""
        import namer

        valid = set(namer.list_categories())
        cats = _default_categories_for_project("testproj")
        for c in cats:
            assert c in valid

    def test_deterministic(self) -> None:
        """Same project ID always produces the same categories."""
        cats1 = _default_categories_for_project("stable-proj")
        cats2 = _default_categories_for_project("stable-proj")
        assert cats1 == cats2

    def test_different_projects_differ(self) -> None:
        """Different project IDs (usually) produce different category sets."""
        cats_a = _default_categories_for_project("project-alpha")
        cats_b = _default_categories_for_project("project-beta")
        # Not guaranteed, but overwhelmingly likely with 25-choose-3
        assert cats_a != cats_b


class TestResolveNameCategories:
    """Tests for _resolve_name_categories()."""

    def test_project_override(self) -> None:
        """Per-project tasks.name_categories takes precedence."""
        project_id = "proj_cat1"
        yml = (
            f"project:\n  id: {project_id}\ntasks:\n  name_categories:\n    - animals\n    - food\n"
        )
        with project_env(yml, project_id=project_id):
            cats = _resolve_name_categories(project_id)
            assert cats == ["animals", "food"]

    @unittest.mock.patch("terok.lib.core.config.get_task_name_categories")
    def test_global_config_fallback(self, mock_global: unittest.mock.Mock) -> None:
        """Global config is used when project has no override."""
        mock_global.return_value = ["music", "sports"]
        project_id = "proj_cat2"
        yml = f"project:\n  id: {project_id}\n"
        with project_env(yml, project_id=project_id):
            cats = _resolve_name_categories(project_id)
            assert cats == ["music", "sports"]

    @unittest.mock.patch("terok.lib.core.config.get_task_name_categories")
    def test_hash_default_fallback(self, mock_global: unittest.mock.Mock) -> None:
        """Hash-based default is used when neither project nor global config is set."""
        mock_global.return_value = None
        project_id = "proj_cat3"
        yml = f"project:\n  id: {project_id}\n"
        with project_env(yml, project_id=project_id):
            cats = _resolve_name_categories(project_id)
            assert len(cats) == 3
            # Should match the deterministic hash output
            assert cats == _default_categories_for_project(project_id)


class TestGenerateTaskNameWithCategories:
    """Tests for generate_task_name() with project_id category resolution."""

    def test_generate_without_project_id(self) -> None:
        """generate_task_name() without project_id still works."""
        name = generate_task_name()
        assert isinstance(name, str)
        assert re.search(r"^[a-z]+-[a-z0-9]+$", name)

    def test_generate_with_project_id(self) -> None:
        """generate_task_name(project_id) uses resolved categories."""
        project_id = "proj_gen_cat"
        yml = f"project:\n  id: {project_id}\ntasks:\n  name_categories:\n    - animals\n"
        with project_env(yml, project_id=project_id):
            name = generate_task_name(project_id)
            assert isinstance(name, str)
            assert re.search(r"^[a-z]+-[a-z0-9]+$", name)

    def test_task_new_uses_project_categories(self) -> None:
        """task_new() passes project_id to generate_task_name for category resolution."""
        project_id = "proj_new_cat"
        yml = f"project:\n  id: {project_id}\n"
        with project_env(yml, project_id=project_id):
            task_new(project_id)
            tasks = get_tasks(project_id)
            assert len(tasks) == 1
            assert tasks[0].name is not None
            assert re.search(r"^[a-z]+-[a-z]+$", tasks[0].name)
