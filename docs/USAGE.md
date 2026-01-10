# codexctl User Guide

A prefix-/XDG-aware tool to manage containerized AI agent projects using Podman. Provides a CLI (`codexctl`) and a Textual TUI (`codextui`).

## Table of Contents

- [Installation](#installation)
- [Runtime Locations](#runtime-locations)
- [Global Configuration](#global-configuration)
- [From Zero to First Run](#from-zero-to-first-run)
- [GPU Passthrough](#gpu-passthrough)
- [Tips](#tips)
- [FAQ](#faq)

---

## Installation

### Via pip

```bash
# Build from source
python -m pip install --upgrade build
python -m build
pip install dist/codexctl-*.whl

# Or install directly (editable for development)
pip install -e .

# With TUI support
pip install '.[tui]'
```

After install, you should have console scripts: `codexctl`, `codexctl-tui`, `codextui`

### Bash Completion

Bash completion is powered by argcomplete.

- If your system has bash-completion installed (common on most distros), completion is enabled automatically
- Manual setup:
  - One-time system-wide: `sudo activate-global-python-argcomplete`
  - Per-shell: `eval "$(register-python-argcomplete codexctl)"`
  - Per-user: add to `~/.bashrc`: `eval "$(register-python-argcomplete codexctl)"`
- Zsh users:
  ```bash
  autoload -U bashcompinit && bashcompinit
  eval "$(register-python-argcomplete --shell zsh codexctl)"
  ```

### Custom Install Paths

**User-local (no root):**
```bash
pip install --user .
# Binaries go to ~/.local/bin (ensure it's on PATH)
```

**Custom prefix (Debian/Ubuntu):**

On Debian/Ubuntu, pip uses the `posix_local` scheme which inserts `/local` under the prefix.

```bash
# Correct - let pip add /local:
pip install --prefix=/virt/podman .
# Result: /virt/podman/local/bin/codexctl

# Wrong - don't add /local yourself:
pip install --prefix=/virt/podman/local .
# Result: /virt/podman/local/local/bin/codexctl
```

**Virtual environment (recommended):**
```bash
python -m venv .venv && . .venv/bin/activate && pip install .
```

---

## Runtime Locations

### Config/Projects

| Install Type | Path |
|--------------|------|
| Root | `/etc/codexctl/projects` |
| User | `~/.config/codexctl/projects` |
| Override | `CODEXCTL_CONFIG_DIR=/path/to/config` |

### State (writable: tasks, build, gate)

| Install Type | Path |
|--------------|------|
| Root | `/var/lib/codexctl` |
| User | `${XDG_DATA_HOME:-~/.local/share}/codexctl` |
| Override | `CODEXCTL_STATE_DIR=/path/to/state` |

---

## Global Configuration

The tool looks for a global config file in this order (first found wins):

1. `${XDG_CONFIG_HOME:-~/.config}/codexctl/config.yml` (user override)
2. `sys.prefix/etc/codexctl/config.yml` (pip/venv installs)
3. `/etc/codexctl/config.yml` (system default)

### Example Config

Copy from `examples/codexctl-config.yml`:
```bash
mkdir -p ~/.config/codexctl
cp examples/codexctl-config.yml ~/.config/codexctl/config.yml
```

### Minimum Settings

```yaml
ui:
  base_port: 7860           # Default port for UI mode

paths:
  user_projects_root: ~/.config/codexctl/projects
  state_root: ~/.local/share/codexctl
  build_root: ~/.local/share/codexctl/build

git:
  human_name: "Your Name"
  human_email: "your@email.com"
```

---

## From Zero to First Run

### Prerequisites

- Podman installed and working
- OpenSSH client tools (ssh, ssh-keygen) for private Git over SSH

### Step 1: Create Project Directory

```bash
mkdir -p ~/.config/codexctl/projects/myproj
```

### Step 2: Create project.yml

```yaml
# ~/.config/codexctl/projects/myproj/project.yml
project:
  id: myproj
  security_class: online    # or "gatekeeping" for restricted mode

git:
  upstream_url: git@github.com:yourorg/yourrepo.git  # or https://...
  default_branch: main

# Optional: SSH hints for containers
ssh:
  key_name: id_ed25519_myproj  # matches key created by ssh-init

# Optional: Docker include snippet
docker:
  user_snippet_file: user.dockerinclude
```

### Step 3: (Optional) Docker Include Snippet

Create `~/.config/codexctl/projects/myproj/user.dockerinclude`:
```dockerfile
RUN apt-get update && apt-get install -y ripgrep jq && rm -rf /var/lib/apt/lists/*
```

This text is pasted near the end of your project image (L2) Dockerfile.

### Step 4: Generate Dockerfiles

```bash
codexctl generate myproj
```

### Step 5: Build Images

```bash
codexctl build myproj

# Optional: build a dev image from L0 as well
codexctl build myproj --dev
```

### Step 6: Initialize SSH (for private repos)

```bash
codexctl ssh-init myproj
```

This creates:
- An ed25519 keypair named `id_ed25519_myproj`
- A default SSH config with:
  - `IdentitiesOnly yes`
  - `StrictHostKeyChecking accept-new` (avoids interactive prompts)
  - `IdentityFile <generated_private_key>`
  - Host github.com section with `User git`

Use the printed `.pub` key to add a deploy key on your Git host.

**Advanced:** Customize SSH config via template in `project.yml`:
```yaml
ssh:
  config_template: ssh_config.template  # relative or absolute path
```
Supported tokens: `{{IDENTITY_FILE}}`, `{{KEY_NAME}}`, `{{PROJECT_ID}}`

### Step 7: Create and Run a Task

```bash
# Create a new task
codexctl task new myproj
# Output: Created task 1 for project myproj

# List tasks
codexctl task list myproj

# Run in CLI mode (headless agent)
codexctl task run-cli myproj 1

# Or run in UI mode (web interface)
codexctl task run-ui myproj 1 --backend codex
```

### UI Mode Configuration

| Backend | API Key Environment Variable | Optional Model Variable |
|---------|------------------------------|------------------------|
| codex | (uses OpenAI from codex config) | - |
| claude | `CODEXUI_CLAUDE_API_KEY` or `ANTHROPIC_API_KEY` or `CLAUDE_API_KEY` | `CODEXUI_CLAUDE_MODEL` |
| mistral | `CODEXUI_MISTRAL_API_KEY` or `MISTRAL_API_KEY` | `CODEXUI_MISTRAL_MODEL` |

---

## GPU Passthrough

GPU passthrough is a per-project opt-in feature (disabled by default).

### Enable in project.yml

```yaml
run:
  gpus: all   # or true
```

### Requirements

- NVIDIA drivers installed on host
- `nvidia-container-toolkit` with Podman integration
- A CUDA/NVIDIA-capable base image (e.g., NVIDIA HPC SDK or CUDA)

Set the base image in `project.yml`:
```yaml
docker:
  base_image: nvcr.io/nvidia/nvhpc:25.9-devel-cuda13.0-ubuntu24.04
```

When enabled, codexctl adds:
- `--device nvidia.com/gpu=all`
- `NVIDIA_VISIBLE_DEVICES=all`
- `NVIDIA_DRIVER_CAPABILITIES=all`

---

## Tips

- **Show resolved paths:** `codexctl config`
- **Where envs live:** `/var/lib/codexctl/envs` (or as configured under `envs.base_dir`)
- **Shared directories:** See [SHARED_DIRS.md](SHARED_DIRS.md)
- **Security modes:** See [GIT_CACHE_AND_SECURITY_MODES.md](GIT_CACHE_AND_SECURITY_MODES.md)

---

## FAQ

### How do I install with a custom prefix?

See [Custom Install Paths](#custom-install-paths) above.

### Where are templates and scripts stored?

Loaded from Python package resources bundled with the wheel (under `codexctl/resources/`). The application never reads from `/usr/share`.

### How do I enable the TUI?

```bash
pip install 'codexctl[tui]'
```

Then run: `codexctl-tui` or `codextui`

### How do I package for Debian/RPM?

See [PACKAGING.md](PACKAGING.md).

---

## See Also

- [Developer Guide](DEVELOPER.md) - Internal architecture and contributor docs
- [Shared Directories](SHARED_DIRS.md) - Volume mounts and SSH configuration
- [Container Layers](CONTAINER_LAYERS.md) - Docker image architecture
- [Security Modes](GIT_CACHE_AND_SECURITY_MODES.md) - Online vs gatekeeping modes
