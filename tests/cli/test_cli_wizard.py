import unittest
import unittest.mock


class ProjectWizardDispatchTests(unittest.TestCase):
    """Tests for the project-wizard CLI command dispatch."""

    @unittest.mock.patch("luskctl.cli.main.run_wizard")
    def test_project_wizard_dispatch(self, mock_wizard: unittest.mock.Mock) -> None:
        from luskctl.cli.main import _cmd_project_init, main

        with unittest.mock.patch("sys.argv", ["luskctl", "project-wizard"]):
            main()

        mock_wizard.assert_called_once()
        _, kwargs = mock_wizard.call_args
        self.assertIs(kwargs.get("init_fn"), _cmd_project_init)


if __name__ == "__main__":
    unittest.main()
