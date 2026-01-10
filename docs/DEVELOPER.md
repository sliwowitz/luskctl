# Developer Guide

This document covers internal architecture and implementation details for contributors and maintainers of codexctl.

## Container Readiness and Log Streaming

codexctl shows the initial container logs to the user when starting task containers and then automatically detaches once a "ready" condition is met. This improves UX but introduces dependencies that developers must be aware of when changing entry scripts or server behavior.

### CLI Mode (task run-cli)

Readiness is determined from log output. The container initialization script emits marker lines:
- `">> init complete"` (from `resources/scripts/init-ssh-and-repo.sh`)
- `"__CLI_READY__"` (echoed by the run command just before keeping the container alive)

The host follows logs and detaches when either of these markers appears, or after 60 seconds timeout.

**If you modify the init script**, ensure a stable readiness line is preserved, or update the detection in `src/codexctl/lib/tasks.py` (`task_run_cli` and `_stream_initial_logs`).

### UI Mode (task run-ui)

Readiness is determined by log markers, not port probing. The host follows container logs and detaches when it sees specific startup markers from Codex UI:
- Primary marker: `"Codex UI ("` (the main startup banner when HTTP server is ready)
- Secondary marker: `"Logging Codex UI activity"` (log redirection message)

This approach avoids false positives from port binding before actual server readiness. The default entry script is `resources/scripts/codexui-entry.sh` which downloads a pre-built CodexUI distribution tarball and runs the production-ready `dist/server.js` via Node.js.

**If the UI server changes its startup behavior or output format**, you may need to adjust:
- The readiness markers in `src/codexctl/lib/tasks.py` (`_ui_ready` function)
- The exposed/internal port and host port mapping in `src/codexctl/lib/tasks.py` (`task_run_ui`)

### Timeout Behavior

- **CLI**: detaches after readiness marker or 60s timeout
- **UI**: detaches after readiness marker (no timeout by default; follows logs until ready)
- Even on timeout, containers remain running in the background. Users can continue watching logs with `podman logs -f <container>`.

### Key Source Files

| File | Purpose |
|------|---------|
| `src/codexctl/lib/tasks.py` | Host-side logic: `task_run_cli`, `task_run_ui`, `_stream_initial_logs`, `_ui_ready` |
| `src/codexctl/resources/scripts/init-ssh-and-repo.sh` | CLI init marker, SSH setup, repo sync |
| `src/codexctl/resources/scripts/codexui-entry.sh` | UI entry script (runs the UI server) |

**Important**: Changes to startup output or listening ports can affect readiness detection. Keep the readiness semantics stable or adjust codexctl's detection accordingly.

---

## Container Layer Architecture

codexctl builds project containers in three logical layers:

| Layer | Image Name | Purpose |
|-------|------------|---------|
| L0 | `codexctl-l0:<base-tag>` | Development base (Ubuntu 24.04, git, ssh, dev user) |
| L1-CLI | `codexctl-l1-cli:<base-tag>` | Agent tools (Codex, Claude Code, Mistral Vibe) |
| L1-UI | `codexctl-l1-ui:<base-tag>` | UI dependencies and entry script |
| L2 | `<project>:l2-cli`, `<project>:l2-ui` | Project-specific config and user snippets |

L0 and L1 are project-agnostic and cache well; L2 is project-specific.

See [CONTAINER_LAYERS.md](CONTAINER_LAYERS.md) for detailed documentation.

---

## Volume Mounts at Runtime

When a task container starts, codexctl mounts:

| Container Path | Host Source | Purpose |
|----------------|-------------|---------|
| `/workspace` | `<state_root>/tasks/<project>/<task>/workspace` | Per-task workspace |
| `/home/dev/.codex` | `<envs_base>/_codex-config` | Codex credentials |
| `/home/dev/.claude` | `<envs_base>/_claude-config` | Claude Code credentials |
| `/home/dev/.vibe` | `<envs_base>/_vibe-config` | Mistral Vibe credentials |
| `/home/dev/.blablador` | `<envs_base>/_blablador-config` | Blablador credentials |
| `/home/dev/.ssh` (optional) | `<envs_base>/_ssh-config-<project>` | SSH keys/config |

See [SHARED_DIRS.md](SHARED_DIRS.md) for detailed documentation.

---

## Environment Variables Set by codexctl

### Core Variables (always set)

| Variable | Value | Purpose |
|----------|-------|---------|
| `PROJECT_ID` | Project ID from config | Identify current project |
| `TASK_ID` | Numeric task ID | Identify current task |
| `REPO_ROOT` | `/workspace` | Init script clone target |
| `CLAUDE_CONFIG_DIR` | `/home/dev/.claude` | Claude Code config location |
| `GIT_RESET_MODE` | `none` (default) | Controls workspace reset behavior |
| `HUMAN_GIT_NAME` | From config or "Nobody" | Git committer name |
| `HUMAN_GIT_EMAIL` | From config or "nobody@localhost" | Git committer email |

### Conditional Variables (based on security mode)

| Variable | When Set | Purpose |
|----------|----------|---------|
| `CODE_REPO` | Always | Git URL (upstream or gate depending on mode) |
| `GIT_BRANCH` | Always | Target branch name |
| `CLONE_FROM` | Online mode with gate | Alternate clone source for faster init |
| `EXTERNAL_REMOTE_URL` | Relaxed gatekeeping | Upstream URL for "external" remote |

---

## Security Modes

### Online Mode
- `CODE_REPO` points to upstream URL
- Container can push directly to upstream
- Git gate (if present) is used as read-only clone accelerator

### Gatekeeping Mode
- `CODE_REPO` points to `file:///git-gate/gate.git`
- Container cannot access upstream directly
- Human review required before changes reach upstream

See [GIT_CACHE_AND_SECURITY_MODES.md](GIT_CACHE_AND_SECURITY_MODES.md) for detailed documentation.

---

## Development Workflow

### Initial Setup

```bash
# Clone the repository
git clone git@github.com:sliwowitz/codexctl.git
cd codexctl

# Install all development dependencies
make install-dev
```

### Before You Commit

**Always run the linter before committing:**

```bash
make lint      # Check for issues (fast, ~1 second)
```

If linting fails, auto-fix with:

```bash
make format    # Auto-fix lint issues and format code
```

**Run tests before pushing** (or at least before opening a PR):

```bash
make test      # Run full test suite with coverage
```

To run both (equivalent to CI):

```bash
make check     # Runs lint + test
```

### Available Make Targets

| Command | Description | When to Use |
|---------|-------------|-------------|
| `make lint` | Check linting and formatting | Before every commit |
| `make format` | Auto-fix lint issues and format | When lint fails |
| `make test` | Run tests with coverage | Before pushing |
| `make check` | Run lint + test | Before opening a PR |
| `make docs` | Serve documentation locally | When editing docs |
| `make install-dev` | Install all dependencies | Initial setup |
| `make clean` | Remove build artifacts | When needed |

### Running from Source

```bash
# Set up environment to use example projects
export CODEXCTL_CONFIG_DIR=$PWD/examples
export CODEXCTL_STATE_DIR=$PWD/tmp/dev-runtime/var-lib-codexctl

# Run CLI commands
python -m codexctl.cli projects
python -m codexctl.cli task new uc
python -m codexctl.cli generate uc
python -m codexctl.cli build uc

# Run TUI
python -m codexctl.tui
```

### IDE Setup (PyCharm/VSCode)

1. Open the repo and set up a Python 3.12+ interpreter
2. Set environment variables:
   - `CODEXCTL_CONFIG_DIR` = `/path/to/this/repo/examples`
   - Optional: `CODEXCTL_STATE_DIR` = writable path
3. For PyCharm Run/Debug configuration:
   - CLI: Module name = `codexctl.cli`, Parameters = `projects` (or other subcommands)
   - TUI: Module name = `codexctl.tui` (no args)

### Building Wheels

```bash
# Build wheel
python -m pip install --upgrade build
python -m build

# Install in development mode (editable)
pip install -e .
```

---

## Packaging

See [PACKAGING.md](PACKAGING.md) for details on:
- Python packaging (pip/Poetry)
- Distribution packages (deb/rpm)
- FHS compliance
- Runtime lookup strategy
