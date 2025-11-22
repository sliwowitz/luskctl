Shared directories and mounts used by codexctl tasks

Overview
- When you run a task (CLI or UI), codexctl starts a container and mounts a small set of host directories into it. This enables:
  - A host-visible workspace where the project repository is cloned (/workspace)
  - Shared credentials/config for Codex under /home/dev/.codex
  - Optional per‑project SSH configuration under /home/dev/.ssh (read‑only)

Per‑task workspace (required)
- Host path: <state_root>/tasks/<project_id>/<task_id>/workspace
  - Created automatically by codexctl when the task runs
  - Mounted as: <host_dir>:/workspace:Z
- Purpose: The project repository is cloned or synced here by init-ssh-and-repo.sh. Because this path lives under the task’s directory on the host, you can inspect, edit, or back it up from the host.

Shared envs base directory (configurable)
- Base dir (default): /var/lib/codexctl/envs
  - Can be overridden in the global config file (codexctl-config.yml):
    envs:
      base_dir: /var/lib/codexctl/envs
- Under this base, two subdirectories may be used:
  1) _codex-config (required; created automatically if missing)
     - Mounted as: <base_dir>/_codex-config → /home/dev/.codex:Z (read‑write)
     - Purpose: Shared credentials/config used by Codex-enabled tools inside the containers.
  2) _ssh-config-<project_id> (optional)
     - Mounted as: <base_dir>/_ssh-config-<project_id> → /home/dev/.ssh:Z,ro (read‑only)
     - Purpose: If your project uses private git URLs (e.g. git@github.com:...), provide SSH keys and config here so the container can fetch the repository.

Expected contents of the optional SSH config directory
- Directory: <base_dir>/_ssh-config-<project_id>
- Files:
  - Private/public key pair for the project (e.g. id_ed25519_<project>, id_ed25519_<project>.pub)
  - config file with host definitions and IdentityFile entries
- Permissions: The directory is mounted read‑only to /home/dev/.ssh in the container. The init script (running as root) will copy the key and config to /root/.ssh with secure permissions and, if available, warm up known_hosts for github.com.
- Key selection: The init script relies on SSH_KEY_NAME if provided in the image/env, but your config file can also refer to the correct IdentityFile.

SELinux and mount flags
- codexctl uses the :Z flag for all volume mounts to ensure correct SELinux labeling. The SSH directory is mounted with :Z,ro to enforce read‑only access.

Quick reference (runtime mounts)
- /workspace              ← <state_root>/tasks/<project>/<task>/workspace:Z
- /home/dev/.codex        ← <envs_base>/_codex-config:Z
- /home/dev/.ssh (optional) ← <envs_base>/_ssh-config-<project>:Z,ro

How codexctl discovers these paths
- state_root: Determined by CODEXCTL_STATE_DIR or defaults (root: /var/lib/codexctl; user: ${XDG_DATA_HOME:-~/.local/share}/codexctl).
- envs_base: Set in codexctl-config.yml under envs.base_dir; defaults to /var/lib/codexctl/envs if unspecified.

Minimal setup to run tasks
1) Ensure codexctl can write to the state root (or set CODEXCTL_STATE_DIR accordingly).
2) Optionally create the envs base dir (codexctl will create _codex-config automatically if missing):
   - sudo mkdir -p /var/lib/codexctl/envs/_codex-config
3) If using private git repositories for a project <proj>:
   - sudo mkdir -p /var/lib/codexctl/envs/_ssh-config-<proj>
   - Place SSH keys and config there (see above). Keys must match your repo host.

Notes
- The SSH directory is optional. Public HTTPS repos do not require it.
- The .codex directory is mounted read‑write and should contain any credentials/config required by Codex tooling.
- Both CLI and UI containers mount the same paths and start with the working directory set to /workspace.
