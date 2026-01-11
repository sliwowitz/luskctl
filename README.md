# luskctl

A tool for managing containerized AI coding agent projects using Podman. Provides both a CLI (`luskctl`) and a Textual TUI (`lusktui`).

> **Future plans and design documents** are in [`docs/brainstorming/`](docs/brainstorming/).

> Similar project also listed on https://github.com/milisp/awesome-codex-cli

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
- Python 3.12+
- OpenSSH client (for private git repos)

### Installation

```bash
# Clone and install
git clone git@github.com:sliwowitz/luskctl.git
cd luskctl
pip install .

# With TUI support
pip install '.[tui]'
```

### Basic Workflow

```bash
# 1. Create project directory
mkdir -p ~/.config/luskctl/projects/myproj

# 2. Create project.yml (see docs/USAGE.md for full schema)
cat > ~/.config/luskctl/projects/myproj/project.yml << 'EOF'
project:
  id: myproj
  security_class: online
git:
  upstream_url: https://github.com/yourorg/yourrepo.git
  default_branch: main
EOF

# 3. Generate and build images
luskctl generate myproj
luskctl build myproj

# 4. (Optional) Set up SSH for private repos
luskctl ssh-init myproj

# 5. Create and run a task
luskctl task new myproj
luskctl task run-cli myproj 1    # CLI mode
# or
luskctl task run-ui myproj 1     # Web UI mode
```

### Common Commands

```bash
luskctl projects              # List projects
luskctl config                # Show resolved paths
luskctl task list <project>   # List tasks
luskctl task delete <project> <task_id>  # Delete a task
```

## Configuration

### Global Config

Location: `~/.config/luskctl/config.yml`

```yaml
ui:
  base_port: 7860

paths:
  user_projects_root: ~/.config/luskctl/projects
  state_root: ~/.local/share/luskctl

git:
  human_name: "Your Name"
  human_email: "your@email.com"
```

### Environment Overrides

| Variable | Purpose |
|----------|---------|
| `LUSKCTL_CONFIG_DIR` | Projects directory |
| `LUSKCTL_STATE_DIR` | Writable state root |
| `LUSKCTL_CONFIG_FILE` | Global config file path |

## Requirements

- **Podman** is required for build/run commands
- **TUI** is optional: `pip install 'luskctl[tui]'`

## Contributing

```bash
# Setup
git clone git@github.com:sliwowitz/luskctl.git && cd luskctl
make install-dev

# Before committing
make lint      # Run linter (required)
make format    # Auto-fix issues if lint fails

# Before pushing
make test      # Run tests
```

See [Developer Guide](docs/DEVELOPER.md) for full details.

## License

See [LICENSE](LICENSE) file.
