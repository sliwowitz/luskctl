"""ProjectActionsMixin — project infrastructure actions for LuskTUI.

Handles project setup (generate, build, ssh-init, gate-sync), authentication,
and the project wizard.  Also provides shared TUI helpers used by both
project and task actions.
"""

import os
import subprocess
import sys
from collections.abc import Callable

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
from .shell_launch import launch_login


class ProjectActionsMixin:
    """Project infrastructure and shared action helpers for LuskTUI.

    Provides ``action_*`` methods for project-level operations (Dockerfile
    generation, image building, SSH init, gate sync, auth, wizard) as well
    as reusable helpers (``_run_suspended``, ``_launch_terminal_session``,
    ``_prompt_ui_backend``) used by both project and task actions.
    """

    # ---------- Shared helpers ----------

    def _prompt_ui_backend(self) -> str:
        """Prompt the user to select a web UI backend and return the choice."""
        backends = list(WEB_BACKENDS)
        default = os.environ.get("DEFAULT_AGENT", "").strip().lower()
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

    # ---------- Project infrastructure actions ----------

    async def action_generate_dockerfiles(self) -> None:
        """Generate Dockerfiles for the current project."""
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
            """Run all four setup steps sequentially."""
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
