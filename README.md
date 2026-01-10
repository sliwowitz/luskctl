# codexctl

A tool for managing containerized AI coding agent projects using Podman. Provides both a CLI (`codexctl`) and a Textual TUI (`codextui`).

> **Future plans and design documents** are in [`docs/brainstorming/`](docs/brainstorming/).

## Documentation

| Document | Description |
|----------|-------------|
| [Full Usage Guide](docs/USAGE.md) | Complete user documentation |
| [Developer Guide](docs/DEVELOPER.md) | Internal architecture and contributor docs |
| [Shared Directories](docs/SHARED_DIRS.md) | Volume mounts and SSH configuration |
| [Container Layers](docs/CONTAINER_LAYERS.md) | Docker image architecture |
| [Security Modes](docs/GIT_CACHE_AND_SECURITY_MODES.md) | Online vs gatekeeping modes |
| [Packaging](docs/PACKAGING.md) | pip, deb, and rpm packaging |

## Quick Start

### Prerequisites

- Podman installed and configured
- Python 3.9+
- OpenSSH client (for private git repos)

### Installation

```bash
# Clone and install
git clone git@github.com:sliwowitz/codexctl.git
cd codexctl
pip install .

# With TUI support
pip install '.[tui]'
```

### Basic Workflow

```bash
# 1. Create project directory
mkdir -p ~/.config/codexctl/projects/myproj

# 2. Create project.yml (see docs/USAGE.md for full schema)
cat > ~/.config/codexctl/projects/myproj/project.yml << 'EOF'
project:
  id: myproj
  security_class: online
git:
  upstream_url: https://github.com/yourorg/yourrepo.git
  default_branch: main
EOF

# 3. Generate and build images
codexctl generate myproj
codexctl build myproj

# 4. (Optional) Set up SSH for private repos
codexctl ssh-init myproj

# 5. Create and run a task
codexctl task new myproj
codexctl task run-cli myproj 1    # CLI mode
# or
codexctl task run-ui myproj 1     # Web UI mode
```

### Common Commands

```bash
codexctl projects              # List projects
codexctl config                # Show resolved paths
codexctl task list <project>   # List tasks
codexctl task delete <project> <task_id>  # Delete a task
```

## Configuration

### Global Config

Location: `~/.config/codexctl/config.yml`

```yaml
ui:
  base_port: 7860

paths:
  user_projects_root: ~/.config/codexctl/projects
  state_root: ~/.local/share/codexctl

git:
  human_name: "Your Name"
  human_email: "your@email.com"
```

### Environment Overrides

| Variable | Purpose |
|----------|---------|
| `CODEXCTL_CONFIG_DIR` | Projects directory |
| `CODEXCTL_STATE_DIR` | Writable state root |
| `CODEXCTL_CONFIG_FILE` | Global config file path |

## Requirements

- **Podman** is required for build/run commands
- **TUI** is optional: `pip install 'codexctl[tui]'`

## License

See [LICENSE](LICENSE) file.
