# Agent Guide (luskctl)

## Purpose

`luskctl` manages containerized AI coding agent projects and per-run tasks using Podman. It ships both a CLI (`luskctl`) and a Textual TUI (`luskctl-tui`).

## Technology Stack

- **Language**: Python 3.12+
- **Package Manager**: Poetry
- **Container Runtime**: Podman
- **Testing**: pytest with coverage
- **Linting/Formatting**: ruff
- **Documentation**: MkDocs with Material theme
- **TUI Framework**: Textual

## Repo layout

- `src/luskctl/`: Python package (CLI in `src/luskctl/cli/`, TUI in `src/luskctl/tui/`)
- `tests/`: `pytest` test suite
- `docs/`: user + developer documentation
- `examples/`, `completions/`: sample configs and shell completions

## Build, Lint, and Test Commands

**Before committing:**
```bash
make lint      # Run linter (required before every commit)
make format    # Auto-fix lint issues if lint fails
```

**Before pushing:**
```bash
make test      # Run full test suite with coverage
make check     # Run both lint and test (equivalent to CI)
```

**When `pyproject.toml` changes** (added/removed/changed dependencies):

```bash
poetry lock --no-update   # Regenerate lockfile without upgrading existing deps
make install-dev          # Apply the updated lockfile to your local environment
# Commit both pyproject.toml and poetry.lock together
```

**Other useful commands:**
```bash
make install-dev  # Install all development dependencies
make docs         # Serve documentation locally
make clean        # Remove build artifacts
```

## Coding Standards

- **Style**: Follow ruff configuration in `pyproject.toml`
- **Line length**: 100 characters (enforced by ruff)
- **Imports**: Sorted with isort (part of ruff)
- **Type hints**: Use Python 3.12+ type hints
- **Docstrings**: Use clear docstrings for public APIs
- **Testing**: Add tests for new functionality; maintain coverage

## Development Workflow

1. Make changes in appropriate module (`src/luskctl/`)
2. Run `make lint` frequently during development
3. Add/update tests in `tests/` directory
4. Run `make test` to verify changes
5. Update documentation in `docs/` if needed
6. Run `make check` before pushing

## Key Guidelines

- **Container Readiness**: When modifying init scripts or server startup, preserve readiness markers (see `docs/DEVELOPER.md`)
- **Security Modes**: Understand online vs gatekeeping modes when working with git operations
- **Minimal Changes**: Make surgical, focused changes
- **Existing Tests**: Never remove or modify unrelated tests
- **Dependencies**: Use Poetry for dependency management; avoid adding unnecessary dependencies

## Important Files

- `docs/DEVELOPER.md`: Detailed architecture and implementation guide
- `docs/USAGE.md`: Complete user documentation
- `Makefile`: Build and test automation
- `pyproject.toml`: Project configuration and dependencies

