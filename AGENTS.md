# Agent Guide (luskctl)

## Purpose

`luskctl` manages containerized AI coding agent projects and per-run tasks using Podman. It ships both a CLI
(`luskctl`) and a Textual TUI (`luskctl-tui`).

## Repo layout

- `src/luskctl/`: Python package (CLI in `src/luskctl/cli/`, TUI in `src/luskctl/tui/`)
- `tests/`: `pytest` test suite
- `docs/`: user + developer documentation
- `examples/`, `completions/`: sample configs and shell completions

## Before pushing

Run lint + tests before pushing your branch:

- `make lint`
- `make test` (or `make check` to run both)

If lint fails, auto-fix with `make format`.

