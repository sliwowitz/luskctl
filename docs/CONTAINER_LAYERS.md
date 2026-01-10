Container layering in codexctl

Overview
- codexctl builds project containers in three logical layers. L0 (dev) and L1 (agent) are project‑agnostic and cache well; L2 is project‑specific.

Layers
0. L0 — development base (codexctl-l0:<base-tag>)
   - Based on Ubuntu 24.04 by default (override via docker.base_image).
   - Installs common tooling (git, openssh-client, ripgrep, vim, etc.).
   - Creates /workspace and sets WORKDIR to /workspace.
   - Creates a dev user with passwordless sudo and runs containers as that user.
   - Stages the init-ssh-and-repo.sh script into the image at /usr/local/bin and makes it the default CMD.
   - Exposes environment defaults used by the init script:
     - REPO_ROOT=/workspace
     - GIT_RESET_MODE=none

1. L1 — agent images (codexctl-l1-cli:<base-tag>, codexctl-l1-ui:<base-tag>)
   - Built FROM L0.
   - CLI image installs Codex, Claude Code, Mistral Vibe, and supporting tools.
   - UI image installs UI dependencies and sets CMD to codexui-entry.sh.
   - codexui-entry.sh:
     - Invokes init-ssh-and-repo.sh first (if present) to initialize SSH and the project repo in /workspace.
     - Downloads a pre-built CodexUI distribution tarball containing production-ready assets and dependencies.
     - Starts the UI server directly using the pre-built dist/server.js.
     - If REPO_ROOT exists, cd into it so the UI starts in the project root.

2. L2 — project images (<project>:l2-cli, <project>:l2-ui)
   - Built FROM the corresponding L1 agent image.
   - Adds project‑specific defaults (CODE_REPO, SSH_KEY_NAME, GIT_BRANCH) and the user snippet.
   - Optional manual dev image (<project>:l2-dev) is built FROM L0 when requested.
   - The UI backend is configurable (Codex, Claude, or Mistral). Precedence (highest to lowest):
     1. CLI flag: `codexctl task run-ui --backend <backend>`
     2. Environment variable: `DEFAULT_AGENT` on the host
     3. Per-project config: `default_agent` in project.yml
     4. Global config: `default_agent` in ~/.config/codexctl/config.yml
     5. Default: codex
     - For Claude, provide CODEXUI_CLAUDE_API_KEY (or ANTHROPIC_API_KEY / CLAUDE_API_KEY) and optional CODEXUI_CLAUDE_MODEL.
     - For Mistral, provide CODEXUI_MISTRAL_API_KEY (or MISTRAL_API_KEY) and optional CODEXUI_MISTRAL_MODEL.

Build flow
- codexctl generate <project> renders four Dockerfiles (L0/L1/L2) into the per‑project build directory:
  - L0.Dockerfile
  - L1.cli.Dockerfile
  - L1.ui.Dockerfile
  - L2.Dockerfile
- codexctl build <project> executes podman builds in order:
  1) codexctl-l0:<base-tag> FROM docker.base_image (default: Ubuntu 24.04)
  2) codexctl-l1-cli:<base-tag> FROM codexctl-l0:<base-tag>
  3) codexctl-l1-ui:<base-tag> FROM codexctl-l0:<base-tag>
  4) <project>:l2-cli FROM codexctl-l1-cli:<base-tag> (via --build-arg BASE_IMAGE=...)
  5) <project>:l2-ui FROM codexctl-l1-ui:<base-tag> (via --build-arg BASE_IMAGE=...)
  6) Optional: <project>:l2-dev FROM codexctl-l0:<base-tag> (when `codexctl build --dev` is used)
  - <base-tag> is derived from docker.base_image (sanitized), e.g.:
    - ubuntu:24.04 → ubuntu-24.04
    - nvcr.io/nvidia/nvhpc:25.9-devel-cuda13.0-ubuntu24.04 → nvcr-io-nvidia-nvhpc-25.9-devel-cuda13.0-ubuntu24.04

Runtime behavior (tasks)
- codexctl task run-cli starts <project>:l2-cli; codexctl task run-ui starts <project>:l2-ui.
- Both modes:
  - Mount a per‑task workspace directory from the host to /workspace.
  - Mount a shared codex config directory to /home/dev/.codex (rw).
  - Mount a shared Claude config directory to /home/dev/.claude (rw) and set CLAUDE_CONFIG_DIR=/home/dev/.claude.
  - Mount a shared Mistral Vibe config directory to /home/dev/.vibe (rw).
  - Optionally mount a per‑project SSH config directory to /home/dev/.ssh (rw) if it exists.
  - Set working directory to /workspace.
  - Provide env vars to the init script: REPO_ROOT, CODE_REPO, GIT_BRANCH, GIT_RESET_MODE.
- The init script clones or syncs the project repository into /workspace and, if configured, warms up SSH known_hosts.

GPU support
- GPU passthrough is opt‑in per project (run.gpus in project.yml). When enabled, codexctl adds the necessary Podman flags for NVIDIA GPUs.
