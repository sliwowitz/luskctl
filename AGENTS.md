# Agent Guide (codexctl)

## Purpose

`codexctl` manages containerized AI coding agent projects and per-run tasks using Podman. It ships both a CLI
(`codexctl`) and a Textual TUI (`codexctl-tui`).

## Repo layout

- `src/codexctl/`: Python package (CLI in `src/codexctl/cli/`, TUI in `src/codexctl/tui/`)
- `tests/`: `pytest` test suite
- `docs/`: user + developer documentation
- `examples/`, `completions/`: sample configs and shell completions

## Before pushing

Run lint + tests before pushing your branch:

- `make lint`
- `make test` (or `make check` to run both)

If lint fails, auto-fix with `make format`.

