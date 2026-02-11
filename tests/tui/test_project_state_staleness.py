import importlib
import importlib.util
import sys
import types
from unittest import TestCase, main, mock

from luskctl.lib.git_gate import GateStalenessInfo


def _build_textual_stubs() -> dict[str, types.ModuleType]:
    textual = types.ModuleType("textual")

    def on(*args, **kwargs):
        def decorator(fn):
            return fn

        return decorator

    textual.on = on

    events_mod = types.ModuleType("textual.events")

    class Key:
        pass

    events_mod.Key = Key

    screen_mod = types.ModuleType("textual.screen")

    class ModalScreen:
        def __init__(self, *args, **kwargs) -> None:
            pass

        @classmethod
        def __class_getitem__(cls, item):
            return cls

    class Screen:
        def __init__(self, *args, **kwargs) -> None:
            pass

        @classmethod
        def __class_getitem__(cls, item):
            return cls

    screen_mod.ModalScreen = ModalScreen
    screen_mod.Screen = Screen

    app_mod = types.ModuleType("textual.app")

    class App:
        def __init__(self, *args, **kwargs) -> None:
            pass

    class ComposeResult:
        pass

    app_mod.App = App
    app_mod.ComposeResult = ComposeResult

    containers_mod = types.ModuleType("textual.containers")

    class Horizontal:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class Vertical:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class VerticalScroll:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    containers_mod.Horizontal = Horizontal
    containers_mod.Vertical = Vertical
    containers_mod.VerticalScroll = VerticalScroll

    widgets_mod = types.ModuleType("textual.widgets")

    class Button:
        class Pressed:
            def __init__(self, *args, **kwargs) -> None:
                pass

        def __init__(self, *args, **kwargs) -> None:
            pass

    class Footer:
        pass

    class Header:
        pass

    class ListItem:
        def __init__(self, *args, **kwargs) -> None:
            pass

    class ListView:
        class Selected:
            def __init__(self, *args, **kwargs) -> None:
                pass

        class Highlighted:
            def __init__(self, *args, **kwargs) -> None:
                pass

        def __init__(self, *args, **kwargs) -> None:
            pass

    class Static:
        def __init__(self, *args, **kwargs) -> None:
            pass

    class OptionList:
        class OptionSelected:
            def __init__(self, *args, **kwargs) -> None:
                pass

        def __init__(self, *args, **kwargs) -> None:
            pass

    widgets_mod.Button = Button
    widgets_mod.Footer = Footer
    widgets_mod.Header = Header
    widgets_mod.ListItem = ListItem
    widgets_mod.ListView = ListView
    widgets_mod.Static = Static
    widgets_mod.OptionList = OptionList

    option_list_mod = types.ModuleType("textual.widgets.option_list")

    class Option:
        def __init__(self, *args, **kwargs) -> None:
            pass

    option_list_mod.Option = Option

    message_mod = types.ModuleType("textual.message")

    class Message:
        pass

    message_mod.Message = Message

    worker_mod = types.ModuleType("textual.worker")

    class Worker:
        class StateChanged:
            def __init__(self, *args, **kwargs) -> None:
                pass

        pass

    class WorkerState:
        SUCCESS = "success"
        ERROR = "error"

    worker_mod.Worker = Worker
    worker_mod.WorkerState = WorkerState

    binding_mod = types.ModuleType("textual.binding")

    class Binding:
        def __init__(self, *args, **kwargs) -> None:
            pass

    binding_mod.Binding = Binding

    textual.events = events_mod
    textual.screen = screen_mod

    return {
        "textual": textual,
        "textual.events": events_mod,
        "textual.screen": screen_mod,
        "textual.app": app_mod,
        "textual.containers": containers_mod,
        "textual.widgets": widgets_mod,
        "textual.widgets.option_list": option_list_mod,
        "textual.message": message_mod,
        "textual.worker": worker_mod,
        "textual.binding": binding_mod,
    }


class ProjectStateStalenessTests(TestCase):
    def test_staleness_checked_for_online_and_gatekeeping(self) -> None:
        stubs = _build_textual_stubs()
        real_find_spec = importlib.util.find_spec

        def _find_spec(name: str, *args, **kwargs):
            if name == "textual":
                return mock.Mock()
            return real_find_spec(name, *args, **kwargs)

        with mock.patch("importlib.util.find_spec", side_effect=_find_spec):
            with mock.patch.dict(sys.modules, stubs):
                for mod_name in list(sys.modules):
                    if mod_name.startswith("luskctl.tui"):
                        sys.modules.pop(mod_name, None)
                app = importlib.import_module("luskctl.tui.app")

                staleness = GateStalenessInfo(
                    branch="main",
                    gate_head="aaa",
                    upstream_head="bbb",
                    is_stale=True,
                    commits_behind=1,
                    last_checked="now",
                    error=None,
                )

                for security_class in ("online", "gatekeeping"):
                    with self.subTest(security_class=security_class):
                        project = mock.Mock()
                        project.security_class = security_class
                        project.upstream_url = "https://example.com/repo.git"

                        state = {"gate": True}

                        with mock.patch.object(app, "load_project", return_value=project):
                            with mock.patch.object(app, "get_project_state", return_value=state):
                                with mock.patch.object(
                                    app, "compare_gate_vs_upstream", return_value=staleness
                                ) as compare:
                                    result = app.LuskTUI._load_project_state(mock.Mock(), "proj1")

                        self.assertEqual(
                            result,
                            ("proj1", project, state, staleness, None),
                        )
                        compare.assert_called_once_with("proj1")


if __name__ == "__main__":
    main()
