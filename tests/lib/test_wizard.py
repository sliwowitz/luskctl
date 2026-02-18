import unittest
import unittest.mock

from luskctl.lib.wizard import (
    _validate_project_id,
    collect_wizard_inputs,
)


class ValidateProjectIdTests(unittest.TestCase):
    """Tests for _validate_project_id()."""

    def test_valid_simple(self) -> None:
        self.assertIsNone(_validate_project_id("myproject"))

    def test_valid_with_hyphens(self) -> None:
        self.assertIsNone(_validate_project_id("my-project"))

    def test_valid_with_underscores(self) -> None:
        self.assertIsNone(_validate_project_id("my_project"))

    def test_valid_with_digits(self) -> None:
        self.assertIsNone(_validate_project_id("proj123"))

    def test_valid_mixed(self) -> None:
        self.assertIsNone(_validate_project_id("My-Project_2"))

    def test_empty_string(self) -> None:
        self.assertIsNotNone(_validate_project_id(""))

    def test_spaces(self) -> None:
        self.assertIsNotNone(_validate_project_id("my project"))

    def test_special_chars(self) -> None:
        self.assertIsNotNone(_validate_project_id("my@project"))

    def test_starts_with_hyphen(self) -> None:
        self.assertIsNotNone(_validate_project_id("-myproject"))

    def test_starts_with_underscore(self) -> None:
        self.assertIsNotNone(_validate_project_id("_myproject"))


class CollectWizardInputsTests(unittest.TestCase):
    """Tests for collect_wizard_inputs()."""

    @unittest.mock.patch(
        "builtins.input", side_effect=["1", "myproj", "https://example.com/r.git", "main", "n"]
    )
    def test_collects_all_values(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        self.assertIsNotNone(result)
        self.assertEqual(result["template_index"], 0)
        self.assertEqual(result["project_id"], "myproj")
        self.assertEqual(result["upstream_url"], "https://example.com/r.git")
        self.assertEqual(result["default_branch"], "main")
        self.assertEqual(result["user_snippet"], "")

    @unittest.mock.patch("builtins.input", side_effect=["3", "gkproj", "git@host:r.git", "", "n"])
    def test_gatekeeping_template_selection(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        self.assertIsNotNone(result)
        self.assertEqual(result["template_index"], 2)

    @unittest.mock.patch(
        "builtins.input", side_effect=["2", "proj", "https://x.com/r.git", "", "n"]
    )
    def test_default_branch_defaults_to_main(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        self.assertIsNotNone(result)
        self.assertEqual(result["default_branch"], "main")

    @unittest.mock.patch(
        "builtins.input", side_effect=["2", "proj", "https://x.com/r.git", "dev", "n"]
    )
    def test_custom_branch(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        self.assertEqual(result["default_branch"], "dev")

    @unittest.mock.patch("builtins.input", side_effect=["invalid"])
    def test_invalid_template_returns_none(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        self.assertIsNone(result)

    @unittest.mock.patch("builtins.input", side_effect=["0"])
    def test_out_of_range_template_returns_none(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        self.assertIsNone(result)

    @unittest.mock.patch("builtins.input", side_effect=["5"])
    def test_template_above_range_returns_none(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        self.assertIsNone(result)

    @unittest.mock.patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_ctrl_c_returns_none(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        self.assertIsNone(result)

    @unittest.mock.patch("builtins.input", side_effect=EOFError)
    def test_eof_returns_none(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        self.assertIsNone(result)

    @unittest.mock.patch(
        "builtins.input",
        side_effect=["1", "bad project", "good-id", "https://x.com/r.git", "main", "n"],
    )
    def test_retries_on_invalid_project_id(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        self.assertIsNotNone(result)
        self.assertEqual(result["project_id"], "good-id")

    @unittest.mock.patch(
        "builtins.input",
        side_effect=["1", "proj", "", "https://x.com/r.git", "main", "n"],
    )
    def test_retries_on_empty_upstream_url(self, _input: unittest.mock.Mock) -> None:
        result = collect_wizard_inputs()
        self.assertIsNotNone(result)
        self.assertEqual(result["upstream_url"], "https://x.com/r.git")


if __name__ == "__main__":
    unittest.main()
