"""Tests for TUI detail screens (Phase 2) and rendering helpers."""

import asyncio
from unittest import TestCase, main, mock

from rich.text import Text

from tui.tui_test_helpers import import_app, import_screens, import_widgets, make_key_event


class RenderHelpersTests(TestCase):
    """Tests for the extracted render_* helper functions."""

    def test_render_project_details_returns_text(self) -> None:
        widgets = import_widgets()

        project = mock.Mock()
        project.id = "test-proj"
        project.upstream_url = "https://example.com/repo.git"
        project.security_class = "online"
        project.agents = ["codex"]
        state = {
            "ssh": True,
            "dockerfiles": True,
            "images": True,
            "gate": True,
        }

        result = widgets.render_project_details(project, state, task_count=5)

        self.assertIsInstance(result, Text)
        text_str = str(result)
        self.assertIn("test-proj", text_str)

    def test_render_project_details_none_project(self) -> None:
        widgets = import_widgets()

        result = widgets.render_project_details(None, None)

        self.assertIsInstance(result, Text)
        self.assertIn("No project", str(result))

    def test_render_task_details_returns_text(self) -> None:
        widgets = import_widgets()

        task = widgets.TaskMeta(
            task_id="42",
            mode="cli",
            status="running",
            workspace="/tmp/ws",
            web_port=None,
            backend="codex",
        )

        result = widgets.render_task_details(task, project_id="proj1")

        self.assertIsInstance(result, Text)
        text_str = str(result)
        self.assertIn("42", text_str)

    def test_render_task_details_none_shows_empty_message(self) -> None:
        widgets = import_widgets()

        result = widgets.render_task_details(None, empty_message="Nothing here")

        self.assertIsInstance(result, Text)
        self.assertIn("Nothing here", str(result))

    def test_render_project_loading(self) -> None:
        widgets = import_widgets()

        project = mock.Mock()
        project.id = "myproj"
        project.upstream_url = "https://example.com"
        project.security_class = "online"

        result = widgets.render_project_loading(project, task_count=3)

        self.assertIsInstance(result, Text)
        text_str = str(result)
        self.assertIn("myproj", text_str)

    def test_render_project_loading_none_project(self) -> None:
        widgets = import_widgets()

        result = widgets.render_project_loading(None)

        self.assertIsInstance(result, Text)
        self.assertIn("No project", str(result))

    def test_render_task_details_autopilot_mode(self) -> None:
        widgets = import_widgets()
        task = widgets.TaskMeta(
            task_id="5",
            mode="run",
            status="running",
            workspace="/tmp/ws",
            web_port=None,
        )
        result = widgets.render_task_details(task, project_id="proj1")
        self.assertIsInstance(result, Text)
        text_str = str(result)
        self.assertIn("Autopilot", text_str)
        self.assertIn("podman logs", text_str)

    def test_render_task_details_autopilot_with_exit_code(self) -> None:
        widgets = import_widgets()
        task = widgets.TaskMeta(
            task_id="5",
            mode="run",
            status="completed",
            workspace="/tmp/ws",
            web_port=None,
            exit_code=0,
        )
        result = widgets.render_task_details(task, project_id="proj1")
        text_str = str(result)
        self.assertIn("Exit code: 0", text_str)

    def test_format_task_label_autopilot(self) -> None:
        widgets = import_widgets()
        task = widgets.TaskMeta(
            task_id="3",
            mode="run",
            status="running",
            workspace="/tmp/ws",
            web_port=None,
        )
        task_list = widgets.TaskList()
        label = task_list._format_task_label(task)
        self.assertIn("🚀", label)

    def test_task_meta_exit_code_field(self) -> None:
        widgets = import_widgets()
        task = widgets.TaskMeta(
            task_id="1",
            mode="run",
            status="completed",
            workspace="/tmp/ws",
            web_port=None,
            exit_code=1,
        )
        self.assertEqual(task.exit_code, 1)

    def test_task_meta_exit_code_default_none(self) -> None:
        widgets = import_widgets()
        task = widgets.TaskMeta(
            task_id="1",
            mode="cli",
            status="running",
            workspace="/tmp/ws",
            web_port=None,
        )
        self.assertIsNone(task.exit_code)


class ScreenConstructionTests(TestCase):
    """Tests that screen classes can be instantiated with correct arguments."""

    def test_project_details_screen_construction(self) -> None:
        screens, _ = import_screens()

        project = mock.Mock()
        project.id = "proj1"
        staleness = mock.Mock()

        screen = screens.ProjectDetailsScreen(
            project=project,
            state={"ssh": True},
            task_count=5,
            staleness=staleness,
        )
        self.assertEqual(screen._project, project)
        self.assertEqual(screen._state, {"ssh": True})
        self.assertEqual(screen._task_count, 5)
        self.assertEqual(screen._staleness, staleness)

    def test_task_details_screen_construction(self) -> None:
        screens, widgets = import_screens()

        task = widgets.TaskMeta(
            task_id="7",
            mode="cli",
            status="running",
            workspace="/tmp/ws",
            web_port=None,
            backend="codex",
        )

        screen = screens.TaskDetailsScreen(
            task=task,
            has_tasks=True,
            project_id="proj1",
            image_old=False,
        )
        self.assertEqual(screen._task_meta, task)
        self.assertTrue(screen._has_tasks)
        self.assertEqual(screen._project_id, "proj1")
        self.assertFalse(screen._image_old)

    def test_auth_actions_screen_construction(self) -> None:
        screens, _ = import_screens()

        screen = screens.AuthActionsScreen()
        self.assertIsNotNone(screen)

    def test_autopilot_prompt_screen_construction(self) -> None:
        screens, _ = import_screens()
        screen = screens.AutopilotPromptScreen()
        self.assertIsNotNone(screen)

    def test_agent_selection_screen_construction(self) -> None:
        screens, _ = import_screens()
        agents = [
            {"name": "reviewer", "description": "Code reviewer", "default": True},
            {"name": "debugger", "description": "Debugger", "default": False},
        ]
        screen = screens.AgentSelectionScreen(agents)
        self.assertIsNotNone(screen)
        self.assertEqual(len(screen._agents), 2)

    def test_agent_selection_screen_empty_agents(self) -> None:
        screens, _ = import_screens()
        screen = screens.AgentSelectionScreen([])
        self.assertIsNotNone(screen)
        self.assertEqual(len(screen._agents), 0)


class TaskScreenKeyBindingTests(TestCase):
    """Tests for TaskDetailsScreen.on_key case-sensitive dispatch."""

    def test_shift_n_dismisses_task_start_cli(self) -> None:
        screens, _ = import_screens()
        screen = screens.TaskDetailsScreen(task=None, has_tasks=False, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("N")
        screen.on_key(event)
        screen.dismiss.assert_called_once_with("task_start_cli")
        event.stop.assert_called_once()

    def test_shift_w_dismisses_task_start_web(self) -> None:
        screens, _ = import_screens()
        screen = screens.TaskDetailsScreen(task=None, has_tasks=False, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("W")
        screen.on_key(event)
        screen.dismiss.assert_called_once_with("task_start_web")

    def test_shift_c_dismisses_new_always(self) -> None:
        screens, _ = import_screens()
        # C should work even when has_tasks=False
        screen = screens.TaskDetailsScreen(task=None, has_tasks=False, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("C")
        screen.on_key(event)
        screen.dismiss.assert_called_once_with("new")

    def test_shift_h_blocked_without_tasks(self) -> None:
        screens, _ = import_screens()
        screen = screens.TaskDetailsScreen(task=None, has_tasks=False, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("H")
        screen.on_key(event)
        screen.dismiss.assert_not_called()

    def test_shift_h_works_with_tasks(self) -> None:
        screens, _ = import_screens()
        screen = screens.TaskDetailsScreen(task=None, has_tasks=True, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("H")
        screen.on_key(event)
        screen.dismiss.assert_called_once_with("diff_head")

    def test_shift_p_works_with_tasks(self) -> None:
        screens, _ = import_screens()
        screen = screens.TaskDetailsScreen(task=None, has_tasks=True, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("P")
        screen.on_key(event)
        screen.dismiss.assert_called_once_with("diff_prev")

    def test_lowercase_d_blocked_without_tasks(self) -> None:
        screens, _ = import_screens()
        screen = screens.TaskDetailsScreen(task=None, has_tasks=False, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("d")
        screen.on_key(event)
        screen.dismiss.assert_not_called()

    def test_lowercase_d_works_with_tasks(self) -> None:
        screens, _ = import_screens()
        screen = screens.TaskDetailsScreen(task=None, has_tasks=True, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("d")
        screen.on_key(event)
        screen.dismiss.assert_called_once_with("delete")

    def test_lowercase_c_works_with_tasks(self) -> None:
        screens, _ = import_screens()
        screen = screens.TaskDetailsScreen(task=None, has_tasks=True, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("c")
        screen.on_key(event)
        screen.dismiss.assert_called_once_with("cli")

    def test_lowercase_w_works_with_tasks(self) -> None:
        screens, _ = import_screens()
        screen = screens.TaskDetailsScreen(task=None, has_tasks=True, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("w")
        screen.on_key(event)
        screen.dismiss.assert_called_once_with("web")

    def test_lowercase_r_works_with_tasks(self) -> None:
        screens, _ = import_screens()
        screen = screens.TaskDetailsScreen(task=None, has_tasks=True, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("r")
        screen.on_key(event)
        screen.dismiss.assert_called_once_with("restart")

    def test_escape_dismisses_none(self) -> None:
        screens, _ = import_screens()
        screen = screens.TaskDetailsScreen(task=None, has_tasks=False, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("escape")
        screen.on_key(event)
        screen.dismiss.assert_called_once_with(None)

    def test_q_dismisses_none(self) -> None:
        screens, _ = import_screens()
        screen = screens.TaskDetailsScreen(task=None, has_tasks=False, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("q")
        screen.on_key(event)
        screen.dismiss.assert_called_once_with(None)

    def test_unmapped_key_does_nothing(self) -> None:
        screens, _ = import_screens()
        screen = screens.TaskDetailsScreen(task=None, has_tasks=True, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("x")
        screen.on_key(event)
        screen.dismiss.assert_not_called()
        event.stop.assert_not_called()

    def test_shift_a_dismisses_task_start_autopilot(self) -> None:
        screens, _ = import_screens()
        screen = screens.TaskDetailsScreen(task=None, has_tasks=False, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("A")
        screen.on_key(event)
        screen.dismiss.assert_called_once_with("task_start_autopilot")
        event.stop.assert_called_once()

    def test_lowercase_f_works_with_autopilot_task(self) -> None:
        screens, widgets = import_screens()
        task = widgets.TaskMeta(
            task_id="t1", status="running", mode="run", workspace="/w", web_port=None
        )
        screen = screens.TaskDetailsScreen(task=task, has_tasks=True, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("f")
        screen.on_key(event)
        screen.dismiss.assert_called_once_with("follow_logs")

    def test_lowercase_f_ignored_for_non_autopilot_task(self) -> None:
        screens, widgets = import_screens()
        task = widgets.TaskMeta(
            task_id="t1", status="running", mode="cli", workspace="/w", web_port=None
        )
        screen = screens.TaskDetailsScreen(task=task, has_tasks=True, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("f")
        screen.on_key(event)
        screen.dismiss.assert_not_called()

    def test_lowercase_f_blocked_without_tasks(self) -> None:
        screens, _ = import_screens()
        screen = screens.TaskDetailsScreen(task=None, has_tasks=False, project_id="p")
        screen.dismiss = mock.Mock()
        event = make_key_event("f")
        screen.on_key(event)
        screen.dismiss.assert_not_called()


class ActionDispatchTests(TestCase):
    """Tests for action dispatch routing in the app."""

    def test_project_action_dispatch_project_init(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)

        coro = AppClass._handle_project_action(instance, "project_init")
        asyncio.run(coro)

        instance._action_project_init.assert_called_once()

    def test_project_action_dispatch_auth_codex(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)

        coro = AppClass._handle_project_action(instance, "auth_codex")
        asyncio.run(coro)

        instance._action_auth.assert_called_once_with("codex")

    def test_project_action_dispatch_auth_claude(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)

        coro = AppClass._handle_project_action(instance, "auth_claude")
        asyncio.run(coro)

        instance._action_auth.assert_called_once_with("claude")

    def test_project_action_dispatch_auth_mistral(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)

        coro = AppClass._handle_project_action(instance, "auth_mistral")
        asyncio.run(coro)

        instance._action_auth.assert_called_once_with("mistral")

    def test_project_action_dispatch_auth_blablador(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)

        coro = AppClass._handle_project_action(instance, "auth_blablador")
        asyncio.run(coro)

        instance._action_auth.assert_called_once_with("blablador")

    def test_task_action_dispatch_task_start_cli(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)

        coro = AppClass._handle_task_action(instance, "task_start_cli")
        asyncio.run(coro)

        instance._action_task_start_cli.assert_called_once()

    def test_task_action_dispatch_task_start_web(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)

        coro = AppClass._handle_task_action(instance, "task_start_web")
        asyncio.run(coro)

        instance._action_task_start_web.assert_called_once()

    def test_task_action_dispatch_restart(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)

        coro = AppClass._handle_task_action(instance, "restart")
        asyncio.run(coro)

        instance._action_restart_task.assert_called_once()

    def test_task_action_dispatch_diff_head(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)

        coro = AppClass._handle_task_action(instance, "diff_head")
        asyncio.run(coro)

        instance.action_copy_diff_head.assert_called_once()

    def test_task_action_dispatch_diff_prev(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)

        coro = AppClass._handle_task_action(instance, "diff_prev")
        asyncio.run(coro)

        instance.action_copy_diff_prev.assert_called_once()

    def test_task_action_dispatch_existing_actions(self) -> None:
        """Verify existing actions (new, cli, web, delete) still route correctly."""
        app_mod, AppClass = import_app()

        for action, method in [
            ("new", "action_new_task"),
            ("cli", "action_run_cli"),
            ("web", "_action_run_web"),
            ("delete", "action_delete_task"),
        ]:
            with self.subTest(action=action):
                instance = mock.Mock(spec=AppClass)
                coro = AppClass._handle_task_action(instance, action)
                asyncio.run(coro)
                getattr(instance, method).assert_called_once()

    def test_project_action_dispatch_existing_actions(self) -> None:
        """Verify existing project actions still route correctly."""
        app_mod, AppClass = import_app()

        for action, method in [
            ("generate", "action_generate_dockerfiles"),
            ("build", "action_build_images"),
            ("build_agents", "_action_build_agents"),
            ("build_full", "_action_build_full"),
            ("init_ssh", "action_init_ssh"),
            ("sync_gate", "_action_sync_gate"),
        ]:
            with self.subTest(action=action):
                instance = mock.Mock(spec=AppClass)
                coro = AppClass._handle_project_action(instance, action)
                asyncio.run(coro)
                getattr(instance, method).assert_called_once()

    def test_action_run_cli_from_main(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)
        coro = AppClass.action_run_cli_from_main(instance)
        asyncio.run(coro)
        instance._action_task_start_cli.assert_called_once()

    def test_action_run_web_from_main(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)
        coro = AppClass.action_run_web_from_main(instance)
        asyncio.run(coro)
        instance._action_task_start_web.assert_called_once()

    def test_action_delete_task_from_main(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)
        coro = AppClass.action_delete_task_from_main(instance)
        asyncio.run(coro)
        instance.action_delete_task.assert_called_once()

    def test_action_run_autopilot_from_main(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)
        coro = AppClass.action_run_autopilot_from_main(instance)
        asyncio.run(coro)
        instance._action_task_start_autopilot.assert_called_once()

    def test_action_follow_logs_from_main(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)
        coro = AppClass.action_follow_logs_from_main(instance)
        asyncio.run(coro)
        instance._action_follow_logs.assert_called_once()

    def test_task_action_dispatch_autopilot(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)
        coro = AppClass._handle_task_action(instance, "task_start_autopilot")
        asyncio.run(coro)
        instance._action_task_start_autopilot.assert_called_once()

    def test_task_action_dispatch_follow_logs(self) -> None:
        app_mod, AppClass = import_app()
        instance = mock.Mock(spec=AppClass)
        coro = AppClass._handle_task_action(instance, "follow_logs")
        asyncio.run(coro)
        instance._action_follow_logs.assert_called_once()


class ProjectScreenNoneStateTests(TestCase):
    """Tests that ProjectDetailsScreen handles None state correctly."""

    def test_project_screen_stores_none_state(self) -> None:
        screens, _ = import_screens()
        project = mock.Mock()
        project.id = "proj1"
        screen = screens.ProjectDetailsScreen(project=project, state=None, task_count=3)
        self.assertIsNone(screen._state)
        self.assertEqual(screen._task_count, 3)


if __name__ == "__main__":
    main()
