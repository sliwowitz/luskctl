Container layering in codexctl

Overview
- codexctl builds project containers in three logical layers. This keeps the base tools and initialization logic separate from the Codex agent and the web UI, improving cache reuse and making images easier to reason about.

Layers
1. L1 — development base (project:l1)
   - Based on the project-configured base image (docker.base_image in project.yml, applied via the L1 Dockerfile template).
   - Installs common tooling (git, openssh-client, etc.).
   - Creates /workspace and sets WORKDIR to /workspace.
   - Stages the init-ssh-and-repo.sh script into the image at /usr/local/bin and makes it the default CMD.
   - Exposes environment defaults used by the init script:
     - REPO_ROOT=/workspace
     - CODE_REPO=<project upstream URL, if set>
     - SSH_KEY_NAME=<from project.yml if configured>
     - GIT_BRANCH=<project default branch>
     - GIT_RESET_MODE=none

2. L2 — Codex + Claude agents (project:l2)
   - Built FROM the freshly built L1 image (enforced by build_images()).
   - Installs the CLI Codex and Claude Code agents plus supporting tools (nodejs, ripgrep).
   - Does not override CMD: it reuses init-ssh-and-repo.sh from L1, so the container can self-initialize the repo and SSH when it starts.
   - At runtime, codexctl runs the container detached and keeps it alive after init so you can exec into it.

3. L3 — Web UI (project:l3)
   - Built FROM the freshly built L1 image (enforced by build_images()).
   - Installs dependencies for the Codex UI and sets CMD to codexui-entry.sh.
   - Claude Code is not available in the web UI; CLI mode only.
   - codexui-entry.sh:
     - Invokes init-ssh-and-repo.sh first (if present) to initialize SSH and the project repo in /workspace.
     - Syncs the UI repo, installs node dependencies, then starts the UI server.
     - If REPO_ROOT exists, cd into it so the UI starts in the project root.

Build flow
- codexctl generate <project> renders three Dockerfiles (L1/L2/L3) into the per‑project build directory.
- codexctl build <project> executes three podman builds in order:
  1) project:l1 FROM the configured base image
  2) project:l2 FROM project:l1 (via --build-arg BASE_IMAGE=<project>:l1)
  3) project:l3 FROM project:l1 (via --build-arg BASE_IMAGE=<project>:l1)
- This guarantees the init script and common setup from L1 are available in both L2 and L3.

Runtime behavior (tasks)
- codexctl task run-cli starts project:l2; codexctl task run-ui starts project:l3.
- Both modes:
  - Mount a per‑task workspace directory from the host to /workspace.
  - Mount a shared codex config directory to /home/dev/.codex (rw).
  - Mount a shared Claude config directory to /home/dev/.claude (rw) and set CLAUDE_CONFIG_DIR=/home/dev/.claude.
  - Optionally mount a per‑project SSH config directory to /home/dev/.ssh (ro) if it exists.
  - Set working directory to /workspace.
  - Provide env vars to the init script: REPO_ROOT, CODE_REPO, GIT_BRANCH, GIT_RESET_MODE.
- The init script clones or syncs the project repository into /workspace and, if configured, warms up SSH known_hosts.

GPU support
- GPU passthrough is opt‑in per project (run.gpus in project.yml). When enabled, codexctl adds the necessary Podman flags for NVIDIA GPUs.
