codexctl
Simple, prefix-/XDG-aware tool to manage containerized projects and per-run tasks using Podman. Provides a CLI (codexctl) and a Textual TUI (codexctl-tui / codextui).

Quick answers to common questions

- How do I run a quick session from within PyCharm?
  1) Open the repo in PyCharm and set up a Python interpreter (3.9+).
  2) Set environment variables so the app sees the example projects:
     - CODEXCTL_CONFIG_DIR = /path/to/this/repo/examples
       (the examples/ directory contains per-project folders with project.yml)
     - Optional: CODEXCTL_STATE_DIR to a writable path (defaults to ~/.local/share/codexctl)
  3) Create a Run/Debug configuration:
     - For CLI: Module name = codexctl.cli, Parameters = projects (or other subcommands)
       Example to list projects: Run module codexctl.cli with args: projects
       Example to create a task:  Run module codexctl.cli with args: task new uc
     - For the TUI: Module name = codexctl.tui (no args). You can also run the installed console script codexctl-tui or codextui.
     - Ensure the Environment variables are set in the Run config (see step 2).

- How do I package and install via pip?
  - From a clean checkout, build an sdist and wheel:
    - python -m pip install --upgrade build
    - python -m build
    - Artifacts appear under dist/ (codexctl-<ver>.tar.gz and codexctl-<ver>-py3-none-any.whl)
  - Install directly from source (editable) for development:
    - python -m pip install -e .
  - Or install the built wheel:
    - python -m pip install dist/codexctl-<ver>-py3-none-any.whl
    - After install, you should have console scripts:
      - codexctl, codexctl-tui, codextui

- How do I enable Bash completion for codexctl?
  - Bash completion is powered by argcomplete.
  - If your system has bash-completion installed (common on most distros), completion is enabled automatically after installing codexctl: the package ships a loader at share/bash-completion/completions/codexctl that Bash autoloads.
  - If completion does not work (e.g., custom env/venv or no bash-completion package), you can enable it manually:
    - One-time system-wide: sudo activate-global-python-argcomplete
    - Per-shell (current session): eval "$(register-python-argcomplete codexctl)"
    - Per-user (all new shells): add to ~/.bashrc
      - eval "$(register-python-argcomplete codexctl)"
  - Zsh users can use bashcompinit:
    - autoload -U bashcompinit && bashcompinit
    - eval "$(register-python-argcomplete --shell zsh codexctl)"

– How do I install into a custom path, e.g. /usr/local?
  - User-local (no root):
    - python -m pip install --user .
    - Binaries go to ~/.local/bin (ensure it’s on PATH).
  - Custom prefix (Debian/Ubuntu note about “local”):
    - On Debian/Ubuntu, pip uses the posix_local install scheme which inserts a
      trailing "/local" segment under the chosen prefix.
    - Therefore, pick the parent directory as your prefix and let pip add
      "/local" for you.
    - Example (recommended):
      - python -m pip install --prefix=/virt/podman .
      - Resulting layout: /virt/podman/local/bin/codexctl and
        /virt/podman/local/lib/pythonX.Y/dist-packages/...
    - Do NOT append "/local" yourself, or you’ll get a nested path like
      /virt/podman/local/local.
      - Wrong: python -m pip install --prefix=/virt/podman/local .
    - If you want the TUI as well, install the extra:
      - python -m pip install --prefix=/virt/podman '.[tui]'
  - Alternatively, use a virtual environment:
    - python -m venv .venv && . .venv/bin/activate && pip install .

Runtime locations (FHS/XDG)

- Config/projects:
  - Root: /etc/codexctl/projects
  - User: ~/.config/codexctl/projects
  - Override: CODEXCTL_CONFIG_DIR=/path/to/config (if this points directly to a folder containing project subfolders, that’s accepted; if it contains a projects/ subfolder, that is used).
- State (writable: tasks, build, cache):
  - Root: /var/lib/codexctl
  - User: ${XDG_DATA_HOME:-~/.local/share}/codexctl
  - Override: CODEXCTL_STATE_DIR=/path/to/state

Global configuration file

- The tool looks for a global config file in this order (first found wins):
  - ${XDG_CONFIG_HOME:-~/.config}/codexctl/config.yml (user override)
  - sys.prefix/etc/codexctl/config.yml (pip/venv installs)
  - /etc/codexctl/config.yml (system default)
- An example config is provided at examples/codexctl-config.yml. Copy and edit:
  - mkdir -p ~/.config/codexctl && cp examples/codexctl-config.yml ~/.config/codexctl/config.yml
- Minimum global settings include:
  - ui.base_port: default first task port for UI mode
  - paths.user_projects_root: per-user projects directory
  - paths.state_root: writable state root
  - paths.build_root: directory for generated files (renamed from legacy "stage")

FHS note

- /usr/share is read-only and should not be used for writable data. codexctl writes under /var/lib/codexctl (for root installs) or ~/.local/share/codexctl (for users). Templates are read from the Python package resources.

Examples for development

- Use the included examples/ as your config:
  - export CODEXCTL_CONFIG_DIR=$PWD/examples
  - Optionally: export CODEXCTL_STATE_DIR=$PWD/tmp/dev-runtime/var-lib-codexctl
  - Now run:
    - python -m codexctl.cli projects
    - python -m codexctl.cli task new uc
    - python -m codexctl.cli task list uc
    - python -m codexctl.cli generate uc
    - python -m codexctl.cli build uc

From zero to first run (new project)

This is the end‑to‑end sequence to start a new project from a user‑provided directory that contains a project.yml and, optionally, a Docker include snippet.

Prerequisites
- Podman installed and working.
- OpenSSH client tools (ssh, ssh-keygen) if you plan to use private Git over SSH.

1) Create your per‑user projects root (once)
- mkdir -p ~/.config/codexctl/projects

2) Create your project directory and project.yml
- Example layout:
  - ~/.config/codexctl/projects/myproj/project.yml
  - Optional snippet: ~/.config/codexctl/projects/myproj/user.dockerinclude

Minimal project.yml example
```yaml
project:
  id: myproj
  security_class: online
git:
  upstream_url: git@github.com:yourorg/yourrepo.git   # or https://... for public
  default_branch: main
# Optional SSH hints for containers (recommended):
ssh:
  key_name: id_ed25519_myproj  # matches the key created by ssh-init
# Optional: reference your Docker include snippet used at image build time
docker:
  user_snippet_file: user.dockerinclude
```

Optional Docker include snippet (user.dockerinclude)
- This text is pasted near the end of your base image (L1) Dockerfile.
- Example lines you might add:
```
RUN apt-get update && apt-get install -y ripgrep jq && rm -rf /var/lib/apt/lists/*
```

3) Generate Dockerfiles
- codexctl generate myproj

4) Build images
- codexctl build myproj

5) Initialize the shared SSH directory and generate a keypair (only if using private Git over SSH)
- codexctl ssh-init myproj
  - By default creates an ed25519 keypair named id_ed25519_myproj and a default SSH config with:
    - Global defaults:
      - IdentitiesOnly yes
      - StrictHostKeyChecking accept-new (avoids interactive prompts in agents)
      - IdentityFile <generated_private_key> (applies to all hosts by default)
    - Host github.com section with User git (inherits IdentityFile)
  - If your project.yml contains ssh.host_dir, that directory is used; otherwise the default path is <envs_base>/_ssh-config-myproj.
  - Use the printed .pub key to add a deploy key or authorize it on your Git host.
  - Advanced: You can customize the SSH config via a template. In project.yml set:
    ```yaml
    ssh:
      config_template: ssh_config.template  # path relative to the project root or absolute
    ```
    The template supports tokens: {{IDENTITY_FILE}}, {{KEY_NAME}}, {{PROJECT_ID}}.
    If not set, a built‑in template is used (see src/codexctl/resources/templates/ssh_config.template).

6) Create a task (per‑run workspace)
- codexctl task new myproj
  - The command prints the new task ID. You can list tasks with: codexctl task list myproj

7) Run the task
- CLI agent mode (headless):
  - codexctl task run-cli myproj <task_id>
- UI (web) mode:
  - codexctl task run-ui myproj <task_id>

Tips
- Show resolved paths and configuration:
  - codexctl config
- Where envs (SSH and codex config) live by default:
  - /var/lib/codexctl/envs (root) or as configured in examples/codexctl-config.yml under envs.base_dir
- Details on shared directories and SSH mounts:
  - docs/SHARED_DIRS.md

Notes

- Podman is required at runtime for build/run commands.
- The TUI is optional. Install it with: pip install 'codexctl[tui]'.
- For system packaging (deb/rpm), install the wheel and create /etc/codexctl and /var/lib/codexctl with suitable permissions; the app will locate them automatically.

Container readiness and initial log streaming (important for developers)

- codexctl shows the initial container logs to the user when starting task containers and then automatically detaches once a "ready" condition is met (or after a short timeout). This improves UX but introduces dependencies that developers must be aware of when changing entry scripts or server behavior.

- CLI (task run-cli):
  - Readiness is determined from log output. The container initialization script emits a marker line:
    - ">> init complete" (from resources/scripts/init-ssh-and-repo.sh)
  - Additionally, the run command echoes "__CLI_READY__" just before keeping the container alive. The host follows logs and detaches when either of these markers appears.
  - If you modify the init script or change its output, ensure that a stable readiness line is preserved, or update the detection in src/codexctl/lib.py (task_run_cli and _stream_initial_logs).

- UI (task run-ui):
  - Readiness is currently determined by probing the bound localhost port (127.0.0.1:<assigned_port> → container port 7860). The host follows the container logs for a short time and detaches as soon as the TCP port is reachable, or after a timeout.
  - This implies a dependency on the UI process actually listening on PORT (default 7860) and binding to 0.0.0.0 inside the container. The default entry script is resources/scripts/codexui-entry.sh which runs `node server.js` from the CodexUI repo.
  - If the UI server changes its port, bind address, or startup behavior (e.g., delays listening until after long asset builds), you may need to adjust:
    - The exposed/internal port, and the host port mapping in src/codexctl/lib.py (task_run_ui).
    - The readiness timeout in lib.py.
    - Optionally, implement log-marker-based readiness if port probing is insufficient, and then add/guarantee a stable log line in the UI server’s startup output.

- Timeouts and detaching behavior:
  - CLI: detaches after readiness marker or 60s.
  - UI: detaches after port becomes reachable or 30s.
  - Even on timeout, containers remain running in the background. Users can continue watching logs with `podman logs -f <container>`.

- Where to change things:
  - Host-side logic: src/codexctl/lib.py (task_run_cli, task_run_ui, _stream_initial_logs)
  - CLI init marker: src/codexctl/resources/scripts/init-ssh-and-repo.sh
  - UI entry: src/codexctl/resources/scripts/codexui-entry.sh (runs the UI server)

- Important dependency note:
  - Because initial log streaming detaches on a specific readiness condition, changes to the UI or CLI startup output or listening port can affect the host-side readiness detection. When altering the UI server or init scripts, please keep the readiness semantics stable or adjust codexctl’s detection accordingly to avoid regressions where the tool either never detaches or detaches too early.

GPU passthrough configuration (per-project only)

- codexctl can request NVIDIA GPU devices for containers (Podman + nvidia-container-toolkit), but this is a per-project opt-in only. The default is disabled.
- To enable for a project, edit <project>/project.yml and add:
  run:
    gpus: all   # or true
- Important: GPU-enabled projects often require a CUDA/NVIDIA-capable base image (e.g., images built with NVIDIA HPC SDK or CUDA). Choose an appropriate base image in the project's docker.base_image.
- When enabled, codexctl adds flags like --device nvidia.com/gpu=all and NVIDIA_* env vars; ensure the host has NVIDIA drivers and nvidia-container-toolkit with Podman integration.
