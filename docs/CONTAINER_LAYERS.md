Container layering in luskctl

Overview
- luskctl builds project containers in three logical layers. L0 (dev) and L1 (agent) are project‑agnostic and cache well; L2 is project‑specific.

Layers
0. L0 — development base (luskctl-l0:<base-tag>)
   - Based on Ubuntu 24.04 by default (override via docker.base_image).
   - Installs common tooling (git, openssh-client, ripgrep, vim, etc.).
   - Creates /workspace and sets WORKDIR to /workspace.
   - Creates a dev user with passwordless sudo and runs containers as that user.
   - Stages the init-ssh-and-repo.sh script into the image at /usr/local/bin and makes it the default CMD.
   - Exposes environment defaults used by the init script:
     - REPO_ROOT=/workspace
     - GIT_RESET_MODE=none

1. L1 — agent images (luskctl-l1-cli:<base-tag>, luskctl-l1-ui:<base-tag>)
   - Built FROM L0.
   - CLI image installs Codex, Claude Code, Mistral Vibe, and supporting tools.
   - UI image installs UI dependencies, prefetches the LuskUI distribution, and sets CMD to luskui-entry.sh.
   - luskui-entry.sh:
     - Invokes init-ssh-and-repo.sh first (if present) to initialize SSH and the project repo in /workspace.
     - Uses the pre-built CodexUI distribution baked into the image; downloads it at runtime only if missing.
     - Starts the UI server directly using the pre-built dist/server.js.
     - If REPO_ROOT exists, cd into it so the UI starts in the project root.

2. L2 — project images (<project>:l2-cli, <project>:l2-ui)
   - Built FROM the corresponding L1 agent image.
   - Adds project‑specific defaults (CODE_REPO, SSH_KEY_NAME, GIT_BRANCH) and the user snippet.
   - Optional manual dev image (<project>:l2-dev) is built FROM L0 when requested.
   - The UI backend is configurable (Codex, Claude, or Mistral). Precedence (highest to lowest):
     1. CLI flag: `luskctl task run-ui --backend <backend>`
     2. Environment variable: `DEFAULT_AGENT` on the host
     3. Per-project config: `default_agent` in project.yml
     4. Global config: `default_agent` in ~/.config/luskctl/config.yml
     5. Default: codex
     - For Claude, provide LUSKUI_CLAUDE_API_KEY (or ANTHROPIC_API_KEY / CLAUDE_API_KEY) and optional LUSKUI_CLAUDE_MODEL.
     - For Mistral, provide LUSKUI_MISTRAL_API_KEY (or MISTRAL_API_KEY) and optional LUSKUI_MISTRAL_MODEL.

Build flow
- luskctl generate <project> renders four Dockerfiles (L0/L1/L2) into the per‑project build directory:
  - L0.Dockerfile
  - L1.cli.Dockerfile
  - L1.ui.Dockerfile
  - L2.Dockerfile
- luskctl build <project> builds only the L2 project images (reuses existing L0/L1 images):
  1) <project>:l2-cli FROM luskctl-l1-cli:<base-tag> (via --build-arg BASE_IMAGE=...)
  2) <project>:l2-ui FROM luskctl-l1-ui:<base-tag> (via --build-arg BASE_IMAGE=...)
  3) Optional: <project>:l2-dev FROM luskctl-l0:<base-tag> (when `luskctl build --dev` is used)
- luskctl build --agents <project> rebuilds L0+L1+L2 with fresh agent installs:
  1) luskctl-l0:<base-tag> FROM docker.base_image (default: Ubuntu 24.04)
  2) luskctl-l1-cli:<base-tag> FROM luskctl-l0:<base-tag> — with cache bust to force fresh agent downloads
  3) luskctl-l1-ui:<base-tag> FROM luskctl-l0:<base-tag>
  4) <project>:l2-cli FROM luskctl-l1-cli:<base-tag>
  5) <project>:l2-ui FROM luskctl-l1-ui:<base-tag>
  6) Optional: <project>:l2-dev FROM luskctl-l0:<base-tag> (when `--dev` is used)
  - The --agents flag passes a unique AGENT_CACHE_BUST build arg to L1, invalidating the cache
    for agent install layers (codex, claude, opencode) while preserving cache for apt packages.
- luskctl build --full-rebuild <project> does a complete rebuild with no cache:
  - Adds --no-cache to all podman build commands
  - Adds --pull=always to L0 build to fetch latest base image
  - Use when base image or apt packages need updating
- <base-tag> is derived from docker.base_image (sanitized), e.g.:
  - ubuntu:24.04 → ubuntu-24.04
  - nvcr.io/nvidia/nvhpc:25.9-devel-cuda13.0-ubuntu24.04 → nvcr-io-nvidia-nvhpc-25.9-devel-cuda13.0-ubuntu24.04

Runtime behavior (tasks)
- luskctl task run-cli starts <project>:l2-cli; luskctl task run-ui starts <project>:l2-ui.
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
- GPU passthrough is opt‑in per project (run.gpus in project.yml). When enabled, luskctl adds the necessary Podman flags for NVIDIA GPUs.
