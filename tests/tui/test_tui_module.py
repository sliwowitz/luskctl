import sys
import unittest
from unittest import mock

# Mock textual dependencies before importing the TUI module
# This is necessary because the TUI module uses decorators that require textual


class MockMessage:
    """Mock base for textual.message.Message."""

    pass


class MockProjectSelected(MockMessage):
    """Mock for ProjectList.ProjectSelected message."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id


class MockProjectList:
    """Mock for widgets.ProjectList."""

    ProjectSelected = MockProjectSelected


class MockTaskSelected(MockMessage):
    """Mock for TaskList.TaskSelected message."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id


class MockTaskList:
    """Mock for widgets.TaskList."""

    TaskSelected = MockTaskSelected


# Mock the @on decorator to just return the function unchanged
def mock_on_decorator(*args, **kwargs):
    def decorator(fn):
        return fn

    return decorator


# Set up textual mocks
_textual_mock = mock.MagicMock()
_textual_mock.on = mock_on_decorator
sys.modules["textual"] = _textual_mock
sys.modules["textual.app"] = mock.MagicMock()
sys.modules["textual.widgets"] = mock.MagicMock()
sys.modules["textual.containers"] = mock.MagicMock()
sys.modules["textual.message"] = mock.MagicMock()

# Mock the widgets module with our mock classes
_widgets_mock = mock.MagicMock()
_widgets_mock.ProjectList = MockProjectList
_widgets_mock.TaskList = MockTaskList
sys.modules["codexctl.tui.widgets"] = _widgets_mock


class TuiModuleTests(unittest.TestCase):
    def test_tui_main_is_callable(self) -> None:
        import importlib

        # Need to reload if already imported
        if "codexctl.tui.app" in sys.modules:
            del sys.modules["codexctl.tui.app"]
        if "codexctl.tui" in sys.modules:
            del sys.modules["codexctl.tui"]

        module = importlib.import_module("codexctl.tui.app")
        self.assertTrue(callable(getattr(module, "main", None)))
