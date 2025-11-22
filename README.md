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

- How do I install into a custom path, e.g. /usr/local?
  - User-local (no root):
    - python -m pip install --user .
    - Binaries go to ~/.local/bin (ensure it’s on PATH).
  - Custom prefix system-wide (requires appropriate permissions):
    - python -m pip install --prefix=/usr/local .
    - Ensure /usr/local/bin is on PATH; site-packages will be under /usr/local/lib/pythonX.Y/site-packages.
  - Alternatively, use a virtual environment:
    - python -m venv .venv && . .venv/bin/activate && pip install .

Runtime locations (FHS/XDG)

- Config/projects:
  - Root: /etc/codexctl/projects
  - User: ~/.config/codexctl/projects
  - Override: CODEXCTL_CONFIG_DIR=/path/to/config (if this points directly to a folder containing project subfolders, that’s accepted; if it contains a projects/ subfolder, that is used).
- State (writable: tasks, stage, cache):
  - Root: /var/lib/codexctl
  - User: ~/.local/share/codexctl
  - Override: CODEXCTL_STATE_DIR=/path/to/state

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
- The TUI depends on textual (declared in pyproject.toml).
- For system packaging (deb/rpm), install the wheel and create /etc/codexctl and /var/lib/codexctl with suitable permissions; the app will locate them automatically.
