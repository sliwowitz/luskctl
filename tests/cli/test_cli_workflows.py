import unittest
import unittest.mock
from collections.abc import Callable


def _patch_init_steps[T](func: Callable[..., T]) -> Callable[..., T]:
    """Apply project-init step mocks to a test method.

    Mock args are injected as: mock_ssh, mock_pause, mock_gen, mock_build, mock_gate.
    """
    func = unittest.mock.patch("luskctl.cli.main.init_project_ssh")(func)
    func = unittest.mock.patch("luskctl.cli.main.maybe_pause_for_ssh_key_registration")(func)
    func = unittest.mock.patch("luskctl.cli.main.generate_dockerfiles")(func)
    func = unittest.mock.patch("luskctl.cli.main.build_images")(func)
    func = unittest.mock.patch("luskctl.cli.main.sync_project_gate")(func)
    return func


class ProjectInitTests(unittest.TestCase):
    """Tests for the project-init convenience command."""

    @_patch_init_steps
    def test_cmd_project_init_calls_four_steps(
        self, mock_ssh, mock_pause, mock_gen, mock_build, mock_gate
    ) -> None:
        mock_gate.return_value = {"success": True, "path": "/tmp/gate"}

        from luskctl.cli.main import _cmd_project_init

        _cmd_project_init("myproj")

        mock_ssh.assert_called_once_with("myproj")
        mock_pause.assert_called_once_with("myproj")
        mock_gen.assert_called_once_with("myproj")
        mock_build.assert_called_once_with("myproj")
        mock_gate.assert_called_once_with("myproj")

    @_patch_init_steps
    def test_cmd_project_init_calls_in_order(
        self, mock_ssh, mock_pause, mock_gen, mock_build, mock_gate
    ) -> None:
        call_order: list[str] = []
        mock_ssh.side_effect = lambda *a, **kw: call_order.append("ssh")
        mock_pause.side_effect = lambda *a, **kw: call_order.append("pause")
        mock_gen.side_effect = lambda *a, **kw: call_order.append("generate")
        mock_build.side_effect = lambda *a, **kw: call_order.append("build")
        mock_gate.side_effect = lambda *a, **kw: (
            call_order.append("gate"),
            {"success": True, "path": "/tmp/gate"},
        )[-1]

        from luskctl.cli.main import _cmd_project_init

        _cmd_project_init("proj1")

        self.assertEqual(call_order, ["ssh", "pause", "generate", "build", "gate"])

    @_patch_init_steps
    def test_cmd_project_init_gate_failure_raises(
        self, mock_ssh, mock_pause, mock_gen, mock_build, mock_gate
    ) -> None:
        mock_gate.return_value = {"success": False, "errors": ["no upstream_url"]}

        from luskctl.cli.main import _cmd_project_init

        with self.assertRaises(SystemExit) as ctx:
            _cmd_project_init("badproj")
        self.assertIn("Gate sync failed", str(ctx.exception))


class SshPauseTests(unittest.TestCase):
    """Tests for the SSH key registration pause in maybe_pause_for_ssh_key_registration."""

    @unittest.mock.patch("luskctl.lib.facade.load_project")
    @unittest.mock.patch("builtins.input", return_value="")
    def test_pauses_for_ssh_upstream(self, mock_input, mock_load) -> None:
        from luskctl.lib.facade import maybe_pause_for_ssh_key_registration

        for upstream in ("git@github.com:org/repo.git", "ssh://github.com/org/repo.git"):
            mock_input.reset_mock()
            mock_load.return_value = unittest.mock.Mock(upstream_url=upstream)

            maybe_pause_for_ssh_key_registration("sshproj")

            mock_input.assert_called_once_with("Press Enter once the key is registered... ")

    @unittest.mock.patch("luskctl.lib.facade.load_project")
    @unittest.mock.patch("builtins.input", return_value="")
    def test_no_pause_for_https_upstream(self, mock_input, mock_load) -> None:
        from luskctl.lib.facade import maybe_pause_for_ssh_key_registration

        mock_load.return_value = unittest.mock.Mock(upstream_url="https://github.com/org/repo.git")

        maybe_pause_for_ssh_key_registration("httpsproj")

        mock_input.assert_not_called()

    @_patch_init_steps
    def test_project_init_continues_after_pause(
        self, mock_ssh, mock_pause, mock_gen, mock_build, mock_gate
    ) -> None:
        """Verify generate/build/gate-sync all proceed after the pause step."""
        mock_gate.return_value = {"success": True, "path": "/tmp/gate"}

        from luskctl.cli.main import _cmd_project_init

        _cmd_project_init("sshproj")

        mock_ssh.assert_called_once_with("sshproj")
        mock_pause.assert_called_once_with("sshproj")
        mock_gen.assert_called_once_with("sshproj")
        mock_build.assert_called_once_with("sshproj")
        mock_gate.assert_called_once_with("sshproj")


class TaskStartTests(unittest.TestCase):
    """Tests for the 'task start' convenience command."""

    @unittest.mock.patch("luskctl.cli.main.task_run_cli")
    @unittest.mock.patch("luskctl.cli.main.task_new", return_value="42")
    def test_task_start_cli_mode(self, mock_new, mock_run_cli) -> None:
        from luskctl.cli.main import main

        with unittest.mock.patch("sys.argv", ["luskctl", "task", "start", "proj1"]):
            main()

        mock_new.assert_called_once_with("proj1", name=None)
        mock_run_cli.assert_called_once_with("proj1", "42", agents=None, preset=None)

    @unittest.mock.patch("luskctl.cli.main.task_run_web")
    @unittest.mock.patch("luskctl.cli.main.task_new", return_value="7")
    def test_task_start_web_mode(self, mock_new, mock_run_web) -> None:
        from luskctl.cli.main import main

        with unittest.mock.patch("sys.argv", ["luskctl", "task", "start", "proj2", "--web"]):
            main()

        mock_new.assert_called_once_with("proj2", name=None)
        mock_run_web.assert_called_once_with("proj2", "7", backend=None, agents=None, preset=None)

    @unittest.mock.patch("luskctl.cli.main.task_run_web")
    @unittest.mock.patch("luskctl.cli.main.task_new", return_value="3")
    def test_task_start_web_with_backend(self, mock_new, mock_run_web) -> None:
        from luskctl.cli.main import main

        with unittest.mock.patch(
            "sys.argv",
            ["luskctl", "task", "start", "proj3", "--web", "--backend", "gradio"],
        ):
            main()

        mock_new.assert_called_once_with("proj3", name=None)
        mock_run_web.assert_called_once_with(
            "proj3", "3", backend="gradio", agents=None, preset=None
        )

    @unittest.mock.patch("luskctl.cli.main._cmd_project_init")
    def test_project_init_dispatch(self, mock_init) -> None:
        from luskctl.cli.main import main

        with unittest.mock.patch("sys.argv", ["luskctl", "project-init", "myproj"]):
            main()

        mock_init.assert_called_once_with("myproj")

    @unittest.mock.patch("luskctl.cli.main.task_login")
    def test_login_dispatch(self, mock_login) -> None:
        from luskctl.cli.main import main

        with unittest.mock.patch("sys.argv", ["luskctl", "login", "proj1", "1"]):
            main()

        mock_login.assert_called_once_with("proj1", "1")
