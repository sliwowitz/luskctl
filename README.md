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

Notes

- Podman is required at runtime for build/run commands.
- The TUI is optional. Install it with: pip install 'codexctl[tui]'.
- For system packaging (deb/rpm), install the wheel and create /etc/codexctl and /var/lib/codexctl with suitable permissions; the app will locate them automatically.
