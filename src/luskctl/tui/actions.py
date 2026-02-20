"""ActionsMixin — worker-backed operations extracted from LuskTUI.

This mixin class holds all action handler methods that delegate to
``lib/`` functions.  It is mixed into ``LuskTUI`` alongside
``PollingMixin`` to keep ``app.py`` focused on layout and event routing.

The mixin accesses ``self`` attributes defined by ``LuskTUI.__init__``
(e.g. ``current_project_id``, ``current_task``) and ``App`` methods
(``notify``, ``suspend``, ``run_worker``, ``open_url``, etc.).
"""

import os
import subprocess
import sys

from ..lib.auth import blablador_auth, claude_auth, codex_auth, mistral_auth
from ..lib.clipboard import copy_to_clipboard_detailed
from ..lib.config import state_root
from ..lib.docker import build_images, generate_dockerfiles
from ..lib.git_gate import sync_project_gate
from ..lib.projects import load_project
from ..lib.shell_launch import launch_login
from ..lib.ssh import init_project_ssh
from ..lib.task_env import WEB_BACKENDS
from ..lib.tasks import (
    get_login_command,
    get_workspace_git_diff,
    task_delete,
    task_new,
    task_restart,
    task_run_cli,
    task_run_headless,
    task_run_web,
)
from .screens import AgentSelectionScreen, AutopilotPromptScreen
from .widgets import TaskList


class ActionsMixin:
    """Action handler methods for the LuskTUI application.

    Every public ``action_*`` and private ``_action_*`` method that
    delegates to a ``lib/`` function lives here.  The host class must
    provide the standard Textual ``App`` interface plus the instance
    attributes initialised by ``LuskTUI.__init__``.
    """

    # ---------- Helpers ----------

    def _prompt_ui_backend(self) -> str:
        backends = list(WEB_BACKENDS)
        # Check DEFAULT_AGENT first, fall back to LUSKUI_BACKEND
        default = os.environ.get("DEFAULT_AGENT", "").strip().lower()
        if not default:
            default = os.environ.get("LUSKUI_BACKEND", "").strip().lower()
        if not default:
            default = backends[0] if backends else "codex"

        print("Select UI backend:")
        for idx, backend in enumerate(backends, start=1):
            label = backend
            if backend == default:
                label += " (default)"
            print(f"  {idx}) {label}")

        choice = input(f"Backend [{default}]: ").strip()
        if not choice:
            return default
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(backends):
                return backends[idx - 1]
            return default
        return choice.lower()

    # ---------- Worker helpers ----------

    def _queue_task_delete(self, project_id: str, task_id: str) -> None:
        self.run_worker(
            lambda: self._delete_task(project_id, task_id),
            name=f"task-delete:{project_id}:{task_id}",
            group="task-delete",
            thread=True,
            exit_on_error=False,
        )

    def _delete_task(self, project_id: str, task_id: str) -> tuple[str, str, str | None]:
        try:
            task_delete(project_id, task_id)
            return project_id, task_id, None
        except Exception as e:
            return project_id, task_id, str(e)

    # ---------- Project infrastructure actions ----------

    async def action_generate_dockerfiles(self) -> None:
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        with self.suspend():
            try:
                generate_dockerfiles(self.current_project_id)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to LuskTUI] ")
        self.notify(f"Generated Dockerfiles for {self.current_project_id}")
        self._refresh_project_state()

    async def action_build_images(self) -> None:
        """Build only L2 project images (reuses existing L0/L1)."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        with self.suspend():
            try:
                build_images(self.current_project_id)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to LuskTUI] ")
        self.notify(f"Built L2 project images for {self.current_project_id}")
        self._refresh_project_state()

    async def action_init_ssh(self) -> None:
        """Initialize the per-project SSH directory and keypair."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return

        with self.suspend():
            try:
                init_project_ssh(self.current_project_id)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to LuskTUI] ")

        self.notify(f"Initialized SSH dir for {self.current_project_id}")
        self._refresh_project_state()

    async def _action_build_agents(self) -> None:
        """Build L0+L1+L2 with fresh agent installs."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        with self.suspend():
            try:
                build_images(self.current_project_id, rebuild_agents=True)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to LuskTUI] ")
        self.notify(f"Built L0+L1+L2 with fresh agents for {self.current_project_id}")
        self._refresh_project_state()

    async def _action_build_full(self) -> None:
        """Full rebuild with no cache."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        with self.suspend():
            try:
                build_images(self.current_project_id, full_rebuild=True)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to LuskTUI] ")
        self.notify(f"Full rebuild (no cache) completed for {self.current_project_id}")
        self._refresh_project_state()

    async def _action_project_init(self) -> None:
        """Full project setup: ssh-init, generate, build, gate-sync."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        pid = self.current_project_id
        with self.suspend():
            try:
                print(f"=== Full Setup for {pid} ===\n")
                print("Step 1/4: Initializing SSH...")
                init_project_ssh(pid)
                print("\nStep 2/4: Generating Dockerfiles...")
                generate_dockerfiles(pid)
                print("\nStep 3/4: Building images...")
                build_images(pid)
                print("\nStep 4/4: Syncing git gate...")
                res = sync_project_gate(pid)
                if not res["success"]:
                    print(f"\nGate sync failed: {', '.join(res['errors'])}")
                else:
                    print(f"\nGate ready at {res['path']}")
                print("\n=== Full Setup complete! ===")
            except SystemExit as e:
                print(f"\nError during setup: {e}")
            input("\n[Press Enter to return to LuskTUI] ")
        self.notify(f"Full setup completed for {pid}")
        self._refresh_project_state()

    # ---------- Authentication actions ----------

    async def _action_auth(self, agent: str) -> None:
        """Run auth flow for the given agent."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        auth_funcs = {
            "codex": codex_auth,
            "claude": claude_auth,
            "mistral": mistral_auth,
            "blablador": blablador_auth,
        }
        func = auth_funcs.get(agent)
        if not func:
            return
        with self.suspend():
            try:
                func(self.current_project_id)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to LuskTUI] ")
        self.notify(f"Auth completed for {agent}")

    # ---------- Task lifecycle actions ----------

    async def action_new_task(self) -> None:
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        with self.suspend():
            try:
                task_new(self.current_project_id)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to LuskTUI] ")
        await self.refresh_tasks()
        self.notify("Task created.")

    async def action_run_cli(self) -> None:
        if not self.current_project_id or not self.current_task:
            self.notify("No task selected.")
            return
        tid = self.current_task.task_id
        with self.suspend():
            try:
                print(f"Running CLI for {self.current_project_id}/{tid}...\n")
                task_run_cli(self.current_project_id, tid)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to LuskTUI] ")
        await self.refresh_tasks()

    async def action_run_web(self) -> None:
        """Public action for running web UI (delegates to _action_run_web)."""
        await self._action_run_web()

    async def _action_run_web(self) -> None:
        """Run web UI for current task."""
        if not self.current_project_id or not self.current_task:
            self.notify("No task selected.")
            return
        tid = self.current_task.task_id
        with self.suspend():
            try:
                backend = self._prompt_ui_backend()
                print(
                    f"Starting Web UI for {self.current_project_id}/{tid} (backend: {backend})...\n"
                )
                task_run_web(self.current_project_id, tid, backend=backend)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to LuskTUI] ")
        await self.refresh_tasks()

    async def _action_task_start_cli(self) -> None:
        """Create a new task and immediately run CLI agent."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        pid = self.current_project_id
        with self.suspend():
            try:
                task_id = task_new(pid)
                print(f"\nRunning CLI for {pid}/{task_id}...\n")
                task_run_cli(pid, task_id)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to LuskTUI] ")
        await self.refresh_tasks()

    async def _action_task_start_web(self) -> None:
        """Create a new task and immediately run Web UI."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        pid = self.current_project_id
        with self.suspend():
            try:
                task_id = task_new(pid)
                backend = self._prompt_ui_backend()
                print(f"\nStarting Web UI for {pid}/{task_id} (backend: {backend})...\n")
                task_run_web(pid, task_id, backend=backend)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to LuskTUI] ")
        await self.refresh_tasks()

    async def _action_task_start_autopilot(self) -> None:
        """Create a new task and run Claude headlessly (autopilot)."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return

        # Show prompt input screen
        await self.push_screen(
            AutopilotPromptScreen(),
            self._on_autopilot_prompt_result,
        )

    async def _on_autopilot_prompt_result(self, prompt: str | None) -> None:
        """Handle the prompt returned from AutopilotPromptScreen."""
        if not prompt or not self.current_project_id:
            return

        pid = self.current_project_id

        # Load project to check for subagents
        try:
            project = load_project(pid)
        except Exception as e:
            self.notify(f"Error loading project: {e}")
            return

        subagents = project.agent_config.get("subagents", [])

        if subagents:
            # Show agent selection screen
            await self.push_screen(
                AgentSelectionScreen(subagents),
                lambda selected, p=prompt: self._on_agent_selection_result(p, selected),
            )
        else:
            # No agents configured, launch directly
            await self._launch_autopilot(prompt, agents=None)

    async def _on_agent_selection_result(self, prompt: str, selected: list[str] | None) -> None:
        """Handle the agent list returned from AgentSelectionScreen."""
        if selected is None:
            # User cancelled agent selection
            return
        await self._launch_autopilot(prompt, agents=selected)

    async def _launch_autopilot(self, prompt: str, agents: list[str] | None = None) -> None:
        """Launch a headless autopilot task in a background worker."""
        if not self.current_project_id:
            return
        pid = self.current_project_id
        self.notify(f"Starting autopilot task for {pid}...")
        self.run_worker(
            lambda: self._run_headless_worker(pid, prompt, agents),
            name=f"autopilot-launch:{pid}",
            group="autopilot-launch",
            thread=True,
            exit_on_error=False,
        )

    def _run_headless_worker(
        self, project_id: str, prompt: str, agents: list[str] | None
    ) -> tuple[str, str, str | None]:
        """Background worker: launch task_run_headless and return result."""
        try:
            task_id = task_run_headless(project_id, prompt, follow=False, agents=agents)
            return project_id, task_id, None
        except SystemExit as e:
            return project_id, "", str(e)
        except Exception as e:
            return project_id, "", str(e)

    def _start_autopilot_watcher(self, project_id: str, task_id: str) -> None:
        """Spawn a background worker that waits for the container to finish
        and updates task metadata with the exit code."""
        container_name = f"{project_id}-run-{task_id}"
        self.run_worker(
            lambda: self._autopilot_wait_worker(project_id, task_id, container_name),
            name=f"autopilot-wait:{project_id}:{task_id}",
            group="autopilot-wait",
            thread=True,
            exit_on_error=False,
        )

    def _autopilot_wait_worker(
        self, project_id: str, task_id: str, container_name: str
    ) -> tuple[str, str, int | None, str | None]:
        """Background worker: wait for the container to exit and update metadata."""
        try:
            result = subprocess.run(
                ["podman", "wait", container_name],
                capture_output=True,
                text=True,
                timeout=7200,  # 2h safety cap
            )
            exit_code = int(result.stdout.strip()) if result.returncode == 0 else None

            # Update task metadata with exit_code and final status
            meta_dir = state_root() / "projects" / project_id / "tasks"
            meta_path = meta_dir / f"{task_id}.yml"
            if meta_path.is_file():
                import yaml

                meta = yaml.safe_load(meta_path.read_text()) or {}
                if exit_code is not None:
                    meta["exit_code"] = exit_code
                    meta["status"] = "completed" if exit_code == 0 else "failed"
                else:
                    meta["status"] = "failed"
                meta_path.write_text(yaml.safe_dump(meta))

            return project_id, task_id, exit_code, None
        except subprocess.TimeoutExpired:
            return project_id, task_id, None, "Watcher timed out"
        except Exception as e:
            return project_id, task_id, None, str(e)

    async def _action_follow_logs(self) -> None:
        """Follow logs for an autopilot task."""
        if not self.current_project_id or not self.current_task:
            self.notify("No task selected.")
            return
        if self.current_task.mode != "run":
            self.notify("Follow logs is only available for autopilot tasks.")
            return

        pid = self.current_project_id
        tid = self.current_task.task_id
        container_name = f"{pid}-run-{tid}"
        cmd = ["podman", "logs", "-f", container_name]
        title = f"logs:{container_name}"

        method, port = launch_login(cmd, title=title)

        if method == "tmux":
            self.notify(f"Logs opened in tmux window: {container_name}")
        elif method == "terminal":
            self.notify(f"Logs opened in new terminal: {container_name}")
        elif method == "web" and port is not None:
            self.open_url(f"http://localhost:{port}")
            self.notify(f"Logs opened in browser tab: {container_name}")
        else:
            # Fallback: suspend TUI
            with self.suspend():
                try:
                    subprocess.run(cmd)
                except Exception as e:
                    print(f"Error: {e}")
                input("\n[Press Enter to return to LuskTUI] ")
            await self.refresh_tasks()

    async def _action_restart_task(self) -> None:
        """Restart a stopped task container."""
        if not self.current_project_id or not self.current_task:
            self.notify("No task selected.")
            return
        pid = self.current_project_id
        tid = self.current_task.task_id
        with self.suspend():
            try:
                task_restart(pid, tid)
            except SystemExit as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to LuskTUI] ")
        await self.refresh_tasks()

    async def _action_login(self) -> None:
        """Log into the selected task's running container."""
        if not self.current_project_id or not self.current_task:
            self.notify("No task selected.")
            return
        pid = self.current_project_id
        tid = self.current_task.task_id
        try:
            cmd = get_login_command(pid, tid)
        except SystemExit as e:
            self.notify(str(e))
            return

        mode = self.current_task.mode or "cli"
        container_name = f"{pid}-{mode}-{tid}"
        title = f"login:{container_name}"

        method, port = launch_login(cmd, title=title)

        if method == "tmux":
            self.notify(f"Opened in tmux window: {container_name}")
        elif method == "terminal":
            self.notify(f"Opened in new terminal: {container_name}")
        elif method == "web" and port is not None:
            self.open_url(f"http://localhost:{port}")
            self.notify(f"Opened terminal in browser tab: {container_name}")
        else:
            # Fallback: suspend TUI
            with self.suspend():
                try:
                    subprocess.run(cmd)
                except Exception as e:
                    print(f"Error: {e}")
                input("\n[Press Enter to return to LuskTUI] ")
            await self.refresh_tasks()

    # ---------- Task management actions ----------

    async def action_delete_task(self) -> None:
        if not self.current_project_id or not self.current_task:
            self.notify("No task selected.")
            return

        tid = self.current_task.task_id
        if self.current_task.status == "deleting":
            self.notify(f"Task {tid} is already deleting.")
            return

        self._log_debug(f"delete: start project_id={self.current_project_id} task_id={tid}")
        self.notify(f"Deleting task {tid}...")

        self.current_task.status = "deleting"
        task_list = self.query_one("#task-list", TaskList)
        task_list.mark_deleting(tid)
        self._update_task_details()

        self._queue_task_delete(self.current_project_id, tid)

    async def _copy_diff_to_clipboard(self, git_ref: str, label: str) -> None:
        """Common helper to copy a git diff to the clipboard."""
        if not self.current_project_id or not self.current_task:
            self.notify("No task selected.")
            return

        task_id = self.current_task.task_id
        diff = get_workspace_git_diff(self.current_project_id, task_id, git_ref)

        if diff is None:
            self.notify("Failed to get git diff. Is this a git repository?")
            return

        if diff == "":
            self.notify("No changes to copy (working tree clean).")
            return

        result = copy_to_clipboard_detailed(diff)
        if result.ok:
            self.notify(f"Git diff vs {label} copied to clipboard ({len(diff)} characters)")
        else:
            msg = result.error or "Failed to copy to clipboard."
            if result.hint:
                msg = f"{msg}\n{result.hint}"
            self.notify(msg)

    async def action_copy_diff_head(self) -> None:
        """Copy git diff vs HEAD to clipboard."""
        await self._copy_diff_to_clipboard("HEAD", "HEAD")

    async def action_copy_diff_prev(self) -> None:
        """Copy git diff vs previous commit to clipboard."""
        await self._copy_diff_to_clipboard("PREV", "PREV")

    # ---------- Gate sync ----------

    async def action_sync_gate(self) -> None:
        """Manually sync gate from upstream."""
        await self._action_sync_gate()

    async def _action_sync_gate(self) -> None:
        """Sync gate (init if doesn't exist, sync if exists)."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return

        try:
            self.notify("Syncing gate...")

            # Run sync in background worker
            self.run_worker(
                self._sync_gate_worker(self.current_project_id),
                name="gate_sync",
                exclusive=True,
            )

        except Exception as e:
            self.notify(f"Sync error: {e}")

    async def _sync_gate_worker(self, project_id: str) -> None:
        """Background worker to sync gate (init if needed)."""
        try:
            result = sync_project_gate(project_id)
            if project_id == self.current_project_id:
                if result["success"]:
                    if result["created"]:
                        self.notify("Gate created and synced from upstream")
                    else:
                        self.notify("Gate synced from upstream")
                else:
                    self.notify(f"Gate sync failed: {', '.join(result['errors'])}")

            # Refresh state after gate operation
            if project_id == self.current_project_id:
                self._refresh_project_state()

        except Exception as e:
            if project_id == self.current_project_id:
                self.notify(f"Gate operation error: {e}")

    # --- Project wizard ---

    async def action_new_project_wizard(self) -> None:
        """Launch the CLI project wizard in a suspended terminal."""
        with self.suspend():
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "luskctl.cli.main", "project-wizard"],
                    check=False,
                )
                if result.returncode != 0:
                    print(f"Wizard exited with code {result.returncode}")
            except Exception as e:
                print(f"Error: {e}")
            input("\n[Press Enter to return to LuskTUI] ")
        await self.refresh_projects()
        self.notify("Project list refreshed.")

    # --- Main-screen task pane shortcuts (c/w/d) ---

    async def action_run_cli_from_main(self) -> None:
        """Start a new CLI task from the main screen."""
        await self._action_task_start_cli()

    async def action_run_web_from_main(self) -> None:
        """Start a new web task from the main screen."""
        await self._action_task_start_web()

    async def action_delete_task_from_main(self) -> None:
        """Delete the selected task from the main screen."""
        await self.action_delete_task()

    async def action_login_from_main(self) -> None:
        """Login to the selected task from the main screen."""
        await self._action_login()

    async def action_run_autopilot_from_main(self) -> None:
        """Start a new autopilot task from the main screen."""
        await self._action_task_start_autopilot()

    async def action_follow_logs_from_main(self) -> None:
        """Follow logs for the selected autopilot task from the main screen."""
        await self._action_follow_logs()
