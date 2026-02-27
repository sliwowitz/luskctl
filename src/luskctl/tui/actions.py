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
from collections.abc import Callable

from ..lib.containers.agents import parse_md_agent
from ..lib.containers.autopilot import wait_for_container_exit
from ..lib.containers.runtime import container_name
from ..lib.containers.task_runners import (
    task_restart,
    task_run_cli,
    task_run_headless,
    task_run_web,
)
from ..lib.containers.tasks import (
    get_login_command,
    get_workspace_git_diff,
    task_delete,
    task_new,
)
from ..lib.core.config import get_envs_base_dir
from ..lib.core.projects import effective_ssh_key_name, load_project
from ..lib.facade import (
    WEB_BACKENDS,
    authenticate,
    build_images,
    generate_dockerfiles,
    init_project_ssh,
    maybe_pause_for_ssh_key_registration,
    sync_project_gate,
)
from .clipboard import copy_to_clipboard_detailed
from .screens import AgentInfo, AgentSelectionScreen, AutopilotPromptScreen
from .shell_launch import launch_login
from .widgets import TaskList


class ActionsMixin:
    """Action handler methods for the LuskTUI application.

    Every public ``action_*`` and private ``_action_*`` method that
    delegates to a ``lib/`` function lives here.  The host class must
    provide the standard Textual ``App`` interface plus the instance
    attributes initialised by ``LuskTUI.__init__``.
    """

    # ---------- Helpers ----------

    @staticmethod
    def _normalize_subagents(subagents: list[dict]) -> list[AgentInfo]:
        """Resolve ``file:`` shorthand entries into full agent dicts.

        Each entry in *subagents* may be either an inline dict (already has
        ``name``, ``description``, etc.) or a ``file:`` reference whose
        ``name`` and ``description`` live inside the ``.md`` YAML frontmatter.
        This normalises both forms into :class:`AgentInfo` dicts so the UI
        screens always have ``name`` and ``description`` to display.
        """
        result: list[AgentInfo] = []
        for sa in subagents:
            if "file" in sa:
                parsed = parse_md_agent(sa["file"])
                if not parsed:
                    continue
                if "default" in sa:
                    parsed["default"] = sa["default"]
                agent = parsed
            else:
                agent = dict(sa)
            name = agent.get("name")
            if not name:
                continue
            result.append(
                AgentInfo(
                    name=name,
                    description=agent.get("description", ""),
                    default=bool(agent.get("default", False)),
                )
            )
        return result

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

    def _focus_task_after_creation(self, project_id: str, task_id: str) -> None:
        """Persist selection so the newly created task is focused after refresh."""
        self._last_selected_tasks[project_id] = task_id
        self._save_selection_state()

    def _print_sync_gate_ssh_help(self, project_id: str) -> None:
        """Print SSH-specific troubleshooting details for gate sync failures."""
        try:
            project = load_project(project_id)
        except Exception:
            return

        upstream = project.upstream_url or ""
        if not (upstream.startswith("git@") or upstream.startswith("ssh://")):
            return

        ssh_dir = project.ssh_host_dir or (get_envs_base_dir() / f"_ssh-config-{project.id}")
        key_name = effective_ssh_key_name(project, key_type="ed25519")
        pub_key_path = ssh_dir / f"{key_name}.pub"

        print("\nHint: this project uses an SSH upstream.")
        print(
            "Gate sync failures are often caused by a missing SSH key registration on the remote."
        )
        print(f"Public key path: {pub_key_path}")

        if pub_key_path.is_file():
            try:
                pub_key_text = pub_key_path.read_text(encoding="utf-8", errors="ignore").strip()
            except Exception:
                pub_key_text = ""
            if pub_key_text:
                print("Public key:")
                print(f"  {pub_key_text}")
            else:
                print("Public key file exists but is empty.")
        else:
            print(f"Public key file not found at {pub_key_path}.")
            print(f"Run 'luskctl ssh-init {project_id}' to generate it.")

    async def _run_suspended(
        self,
        fn: Callable[[], None],
        *,
        success_msg: str | None = None,
        refresh: str | None = "project_state",
    ) -> bool:
        """Run *fn* in a suspended TUI session with standard error handling.

        Suspends the TUI, runs *fn*, waits for the user to press Enter,
        then optionally notifies and refreshes.  Returns True if *fn*
        completed without error.  The resume prompt is shown in a finally
        block so the user always gets back to the TUI.
        """
        ok = False
        with self.suspend():
            try:
                fn()
                ok = True
            except SystemExit as e:
                print(f"Error: {e}")
            except Exception as e:
                print(f"Error: {e}")
            finally:
                input("\n[Press Enter to return to LuskTUI] ")
        if ok and success_msg:
            self.notify(success_msg)
        if refresh == "project_state":
            self._refresh_project_state()
        elif refresh == "tasks":
            await self.refresh_tasks()
        return ok

    async def _launch_terminal_session(
        self,
        cmd: list[str],
        *,
        title: str,
        cname: str,
        label: str = "Opened",
    ) -> None:
        """Launch *cmd* via tmux/terminal/web, falling back to a suspended TUI."""
        method, port = launch_login(cmd, title=title)

        if method == "tmux":
            self.notify(f"{label} in tmux window: {cname}")
        elif method == "terminal":
            self.notify(f"{label} in new terminal: {cname}")
        elif method == "web" and port is not None:
            self.open_url(f"http://localhost:{port}")
            self.notify(f"{label} in browser: {cname}")
        else:
            with self.suspend():
                try:
                    subprocess.run(cmd)
                except Exception as e:
                    print(f"Error: {e}")
                input("\n[Press Enter to return to LuskTUI] ")
            await self.refresh_tasks()

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
        pid = self.current_project_id
        await self._run_suspended(
            lambda: generate_dockerfiles(pid),
            success_msg=f"Generated Dockerfiles for {pid}",
        )

    async def action_build_images(self) -> None:
        """Build only L2 project images (reuses existing L0/L1)."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        pid = self.current_project_id
        await self._run_suspended(
            lambda: build_images(pid),
            success_msg=f"Built L2 project images for {pid}",
        )

    async def action_init_ssh(self) -> None:
        """Initialize the per-project SSH directory and keypair."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        pid = self.current_project_id
        await self._run_suspended(
            lambda: init_project_ssh(pid),
            success_msg=f"Initialized SSH dir for {pid}",
        )

    async def _action_build_agents(self) -> None:
        """Build L0+L1+L2 with fresh agent installs."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        pid = self.current_project_id
        await self._run_suspended(
            lambda: build_images(pid, rebuild_agents=True),
            success_msg=f"Built L0+L1+L2 with fresh agents for {pid}",
        )

    async def _action_build_full(self) -> None:
        """Full rebuild with no cache."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        pid = self.current_project_id
        await self._run_suspended(
            lambda: build_images(pid, full_rebuild=True),
            success_msg=f"Full rebuild (no cache) completed for {pid}",
        )

    async def _action_project_init(self) -> None:
        """Full project setup: ssh-init, generate, build, gate-sync."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        pid = self.current_project_id

        gate_ok = False

        def work() -> None:
            nonlocal gate_ok
            print(f"=== Full Setup for {pid} ===\n")
            print("Step 1/4: Initializing SSH...")
            init_project_ssh(pid)
            maybe_pause_for_ssh_key_registration(pid)
            print("\nStep 2/4: Generating Dockerfiles...")
            generate_dockerfiles(pid)
            print("\nStep 3/4: Building images...")
            build_images(pid)
            print("\nStep 4/4: Syncing git gate...")
            res = sync_project_gate(pid)
            if not res["success"]:
                print(f"\nGate sync warnings: {', '.join(res['errors'])}")
            else:
                print(f"\nGate ready at {res['path']}")
                gate_ok = True
            print("\n=== Full Setup complete! ===")

        ok = await self._run_suspended(work, refresh="project_state")
        if ok and gate_ok:
            self.notify(f"Full setup completed for {pid}")
        elif ok:
            self.notify(f"Setup done for {pid} (gate sync had errors)", severity="warning")

    # ---------- Authentication actions ----------

    async def _action_auth(self, provider: str) -> None:
        """Run auth flow for the given provider."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        await self._run_suspended(
            lambda: authenticate(self.current_project_id, provider),
            success_msg=f"Auth completed for {provider}",
            refresh=None,
        )

    # ---------- Task lifecycle actions ----------

    async def action_new_task(self) -> None:
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        pid = self.current_project_id

        def work() -> None:
            task_id = task_new(pid)
            self._focus_task_after_creation(pid, task_id)

        await self._run_suspended(work, success_msg="Task created.", refresh="tasks")

    async def action_run_cli(self) -> None:
        if not self.current_project_id or not self.current_task:
            self.notify("No task selected.")
            return
        pid = self.current_project_id
        tid = self.current_task.task_id

        def work() -> None:
            print(f"Running CLI for {pid}/{tid}...\n")
            task_run_cli(pid, tid)

        await self._run_suspended(work, refresh="tasks")

    async def action_run_web(self) -> None:
        """Public action for running web UI (delegates to _action_run_web)."""
        await self._action_run_web()

    async def _action_run_web(self) -> None:
        """Run web UI for current task."""
        if not self.current_project_id or not self.current_task:
            self.notify("No task selected.")
            return
        pid = self.current_project_id
        tid = self.current_task.task_id

        def work() -> None:
            backend = self._prompt_ui_backend()
            print(f"Starting Web UI for {pid}/{tid} (backend: {backend})...\n")
            task_run_web(pid, tid, backend=backend)

        await self._run_suspended(work, refresh="tasks")

    async def _action_task_start_cli(self) -> None:
        """Create a new task and immediately run CLI agent."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        pid = self.current_project_id

        def work() -> None:
            task_id = task_new(pid)
            self._focus_task_after_creation(pid, task_id)
            print(f"\nRunning CLI for {pid}/{task_id}...\n")
            task_run_cli(pid, task_id)

        await self._run_suspended(work, refresh="tasks")

    async def _action_task_start_web(self) -> None:
        """Create a new task and immediately run Web UI."""
        if not self.current_project_id:
            self.notify("No project selected.")
            return
        pid = self.current_project_id

        def work() -> None:
            task_id = task_new(pid)
            self._focus_task_after_creation(pid, task_id)
            backend = self._prompt_ui_backend()
            print(f"\nStarting Web UI for {pid}/{task_id} (backend: {backend})...\n")
            task_run_web(pid, task_id, backend=backend)

        await self._run_suspended(work, refresh="tasks")

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

        raw_subagents = project.agent_config.get("subagents", [])
        subagents = self._normalize_subagents(raw_subagents) if raw_subagents else []

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
        cname = container_name(project_id, "run", task_id)
        self.run_worker(
            lambda: self._autopilot_wait_worker(project_id, task_id, cname),
            name=f"autopilot-wait:{project_id}:{task_id}",
            group="autopilot-wait",
            thread=True,
            exit_on_error=False,
        )

    def _autopilot_wait_worker(
        self, project_id: str, task_id: str, cname: str
    ) -> tuple[str, str, int | None, str | None]:
        """Background worker: wait for the container to exit and update metadata."""
        exit_code, error = wait_for_container_exit(cname, project_id, task_id)
        return project_id, task_id, exit_code, error

    async def _action_follow_logs(self) -> None:
        """View logs for a task in the integrated log viewer."""
        if not self.current_project_id or not self.current_task:
            self.notify("No task selected.")
            return
        task = self.current_task
        if not task.mode:
            self.notify("Task has no mode set (never started).")
            return

        pid = self.current_project_id
        tid = task.task_id
        cname = container_name(pid, task.mode, tid)

        from ..lib.containers.runtime import get_container_state

        state = get_container_state(cname)
        if state is None:
            self.notify(f"No container found for task {tid}.")
            return
        follow = state == "running"

        from .log_viewer import LogViewerScreen

        await self.push_screen(
            LogViewerScreen(
                project_id=pid,
                task_id=tid,
                mode=task.mode,
                container_name=cname,
                follow=follow,
            )
        )

    async def _action_restart_task(self) -> None:
        """Restart a task container (stops it first if running)."""
        if not self.current_project_id or not self.current_task:
            self.notify("No task selected.")
            return
        pid = self.current_project_id
        tid = self.current_task.task_id
        await self._run_suspended(lambda: task_restart(pid, tid), refresh="tasks")

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
        cname = container_name(pid, mode, tid)
        await self._launch_terminal_session(cmd, title=f"login:{cname}", cname=cname)

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

        project_id = self.current_project_id
        sync_ok = False
        with self.suspend():
            try:
                print(f"Syncing gate for {project_id}...")
                result = sync_project_gate(project_id)
                if result["success"]:
                    sync_ok = True
                    if result["created"]:
                        print("Gate created and synced from upstream.")
                    else:
                        print("Gate synced from upstream.")
                else:
                    print(f"Gate sync failed: {', '.join(result['errors'])}")
                    self._print_sync_gate_ssh_help(project_id)
            except SystemExit as e:
                print(f"Gate sync failed: {e}")
                self._print_sync_gate_ssh_help(project_id)
            except Exception as e:
                print(f"Gate operation error: {e}")
                self._print_sync_gate_ssh_help(project_id)
            input("\n[Press Enter to return to LuskTUI] ")

        if sync_ok:
            self.notify("Gate synced from upstream")
        else:
            self.notify("Gate sync failed. See terminal output.")
        self._refresh_project_state()

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
