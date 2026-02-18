import unittest
import unittest.mock


class ProjectWizardDispatchTests(unittest.TestCase):
    """Tests for the project-wizard CLI command dispatch."""

    @unittest.mock.patch("luskctl.cli.main.run_wizard")
    def test_project_wizard_dispatch(self, mock_wizard: unittest.mock.Mock) -> None:
        from luskctl.cli.main import main

        with unittest.mock.patch("sys.argv", ["luskctl", "project-wizard"]):
            main()

        mock_wizard.assert_called_once()


if __name__ == "__main__":
    unittest.main()
