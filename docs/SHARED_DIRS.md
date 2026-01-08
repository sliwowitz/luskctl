Shared directories and mounts used by codexctl tasks

Overview
- When you run a task (CLI or UI), codexctl starts a container and mounts a small set of host directories into it. This enables:
  - A host-visible workspace where the project repository is cloned (/workspace)
  - Shared credentials/config for Codex under /home/dev/.codex
  - Shared credentials/config for Claude Code under /home/dev/.claude
  - Shared credentials/config for Mistral Vibe under /home/dev/.vibe
  - Optional per‑project SSH configuration under /home/dev/.ssh (read‑write)

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
- Under this base, four subdirectories may be used:
  1) _codex-config (required; created automatically if missing)
     - Mounted as: <base_dir>/_codex-config → /home/dev/.codex:Z (read‑write)
     - Purpose: Shared credentials/config used by Codex-enabled tools inside the containers.
  2) _claude-config (required; created automatically if missing)
     - Mounted as: <base_dir>/_claude-config → /home/dev/.claude:Z (read‑write)
     - Purpose: Shared credentials/config used by Claude Code in CLI mode.
     - Note: codexctl sets CLAUDE_CONFIG_DIR=/home/dev/.claude inside containers.
  3) _vibe-config (required; created automatically if missing)
     - Mounted as: <base_dir>/_vibe-config → /home/dev/.vibe:Z (read‑write)
     - Purpose: Shared credentials/config used by Mistral Vibe (CLI + UI).
  4) _ssh-config-<project_id> (optional)
     - Mounted as: <base_dir>/_ssh-config-<project_id> → /home/dev/.ssh:Z (read‑write)
     - Purpose: If your project uses private git URLs (e.g. git@github.com:...), provide SSH keys and config here so the container can fetch the repository.

Expected contents of the optional SSH config directory
- Directory: <base_dir>/_ssh-config-<project_id>
- Files:
  - Private/public key pair for the project (e.g. id_ed25519_<project>, id_ed25519_<project>.pub)
  - config file with host definitions and IdentityFile entries
- Permissions: The directory is mounted read‑write to /home/dev/.ssh in the container. The init script will use the keys and config directly and, if available, warm up known_hosts for github.com only when the project's code repo is hosted on GitHub.
- Key selection: The init script relies on SSH_KEY_NAME if provided in the image/env, but your config file can also refer to the correct IdentityFile.

How to create this directory automatically
- Use the helper command:
  - codexctl ssh-init <project_id> [--key-type ed25519|rsa] [--key-name NAME] [--force]
- What it does:
  - Resolves the target directory for <project_id> as:
    - If <project>/project.yml sets ssh.host_dir → use it; otherwise
    - <envs_base>/_ssh-config-<project_id>
  - Generates an SSH keypair (default: ed25519) and writes a default SSH config:
    - A global section applied to all hosts:
      - Host *
      -   IdentitiesOnly yes
      -   StrictHostKeyChecking accept-new
      -   IdentityFile <generated_private_key>
      - This prevents interactive host‑key prompts (agents are non‑interactive) and ensures the same key is used by default for all hosts.
    - A host section for github.com with User git (inherits IdentityFile from Host *).
  - The SSH config is rendered from a template. You can provide your own template via project.yml → ssh.config_template.
    - Supported tokens in the template: {{IDENTITY_FILE}}, {{KEY_NAME}}, {{PROJECT_ID}}
    - If not provided, a built-in template is used (see src/codexctl/resources/templates/ssh_config.template).
  - Prints the resulting paths. Use the .pub key to register a deploy key or add it to your Git host.

SELinux and mount flags
- codexctl uses the :Z flag for all volume mounts to ensure correct SELinux labeling. The SSH directory is mounted with :Z for read‑write access.

Git identity configuration
- codexctl automatically configures git user.name and user.email inside containers to identify AI-generated commits.
- The identity is set based on the agent type (CODEXCTL_AGENT_TYPE environment variable):
  - codex → "Codex <codex@ai-agent>"
  - claude → "Claude <claude@ai-agent>"
  - mistral (or vibe) → "Mistral <mistral@ai-agent>"
  - blablador → "Blablador <blablador@ai-agent>"
  - (default) → "AI Agent <ai-agent@localhost>"
- For CLI mode (task run-cli), the default agent type is "claude" unless overridden via CODEXCTL_AGENT_TYPE environment variable.
- For UI mode (task run-ui), the agent type matches the --backend parameter (codex, claude, or mistral). When no backend is specified, it defaults to "codex".
- This allows you to quickly distinguish which commits were made by AI agents versus human developers.

Quick reference (runtime mounts)
- /workspace          ← <state_root>/tasks/<project>/<task>/workspace:Z
- /home/dev/.codex        ← <envs_base>/_codex-config:Z
- /home/dev/.claude       ← <envs_base>/_claude-config:Z
- /home/dev/.vibe         ← <envs_base>/_vibe-config:Z
- /home/dev/.ssh (optional) ← <envs_base>/_ssh-config-<project>:Z

How codexctl discovers these paths
- state_root: Determined by CODEXCTL_STATE_DIR or defaults (root: /var/lib/codexctl; user: ${XDG_DATA_HOME:-~/.local/share}/codexctl).
- envs_base: Set in codexctl-config.yml under envs.base_dir; defaults to /var/lib/codexctl/envs if unspecified.

Minimal setup to run tasks
1) Ensure codexctl can write to the state root (or set CODEXCTL_STATE_DIR accordingly).
2) Optionally create the envs base dir (codexctl will create _codex-config, _claude-config, and _vibe-config automatically if missing):
   - sudo mkdir -p /var/lib/codexctl/envs/_codex-config
   - sudo mkdir -p /var/lib/codexctl/envs/_claude-config
   - sudo mkdir -p /var/lib/codexctl/envs/_vibe-config
3) If using private git repositories for a project <proj>:
   - sudo mkdir -p /var/lib/codexctl/envs/_ssh-config-<proj>
   - Place SSH keys and config there (see above). Keys must match your repo host.

Notes
- The SSH directory is optional. Public HTTPS repos do not require it.
- The .codex directory is mounted read‑write and should contain any credentials/config required by Codex tooling.
- The .claude directory is mounted read‑write and should contain any credentials/config required by Claude Code (CLI only).
- The .vibe directory is mounted read‑write and should contain any credentials/config required by Mistral Vibe.
- Both CLI and UI containers mount the same paths and start with the working directory set to /workspace.

See also
- Run `codexctl config` to see the resolved envs base dir and other important paths.
