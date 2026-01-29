# Shared directories and mounts used by luskctl tasks

## Overview
- When you run a task (CLI or UI), luskctl starts a container and mounts a small set of host directories into it. This enables:
  - A host-visible workspace where the project repository is cloned (`/workspace`)
  - Shared credentials/config for Codex under `/home/dev/.codex`
  - Shared credentials/config for Claude Code under `/home/dev/.claude`
  - Shared credentials/config for Mistral Vibe under `/home/dev/.vibe`
  - Shared credentials/config for Blablador (OpenCode) under `/home/dev/.blablador`
  - Shared config directory for OpenCode under `/home/dev/.config/opencode`
  - Shared data directory for OpenCode under `/home/dev/.local/share/opencode`
  - Shared state directory for OpenCode/Bun under `/home/dev/.local/state`
  - Optional per-project SSH configuration under `/home/dev/.ssh` (read-write)

## Per-task workspace (required)
- Host path: `<state_root>/tasks/<project_id>/<task_id>/workspace`
  - Created automatically by luskctl when the task runs
  - Mounted as: `<host_dir>:/workspace:Z`
- Purpose: The project repository is cloned or synced here by `init-ssh-and-repo.sh`. Because this path lives under the task's directory on the host, you can inspect, edit, or back it up from the host.

## Shared envs base directory (configurable)
- Base dir (default): `/var/lib/luskctl/envs`
  - Can be overridden in the global config file (`luskctl-config.yml`):

```yaml
envs:
  base_dir: /var/lib/luskctl/envs
```

- Under this base, eight subdirectories may be used:
  1. `_codex-config` (required; created automatically if missing)
     - Mounted as: `<base_dir>/_codex-config:/home/dev/.codex:z` (read-write)
     - Purpose: Shared credentials/config used by Codex-enabled tools inside the containers.
  2. `_claude-config` (required; created automatically if missing)
     - Mounted as: `<base_dir>/_claude-config:/home/dev/.claude:z` (read-write)
     - Purpose: Shared credentials/config used by Claude Code in CLI mode.
     - Note: luskctl sets `CLAUDE_CONFIG_DIR=/home/dev/.claude` inside containers.
  3. `_vibe-config` (required; created automatically if missing)
     - Mounted as: `<base_dir>/_vibe-config:/home/dev/.vibe:z` (read-write)
     - Purpose: Shared credentials/config used by Mistral Vibe (CLI + UI).
  4. `_blablador-config` (required; created automatically if missing)
     - Mounted as: `<base_dir>/_blablador-config:/home/dev/.blablador:z` (read-write)
     - Purpose: Shared credentials/config used by Blablador (OpenCode wrapper) inside the containers.
  5. `_opencode-config` (required; created automatically if missing)
     - Mounted as: `<base_dir>/_opencode-config:/home/dev/.config/opencode:z` (read-write)
     - Purpose: Shared config directory for OpenCode (contains opencode.json with provider settings).
  6. `_opencode-data` (required; created automatically if missing)
     - Mounted as: `<base_dir>/_opencode-data:/home/dev/.local/share/opencode:z` (read-write)
     - Purpose: Shared data directory used by OpenCode (invoked via the Blablador wrapper) for caches and runtime data.
  7. `_opencode-state` (required; created automatically if missing)
     - Mounted as: `<base_dir>/_opencode-state:/home/dev/.local/state:z` (read-write)
     - Purpose: Shared state directory used by OpenCode and Bun runtime.
  8. `_opencode-custom-config` (optional)
     - Mounted as: `<base_dir>/_opencode-custom-config:/home/dev/.config/opencode-custom:z` (read-write)
     - Purpose: Custom OpenCode provider configurations for local LLM instances.
     - Example: Place your `opencode-custom.json` file here and point to it in `luskctl-config.yml`.
  8. `_ssh-config-<project_id>` (optional)
     - Mounted as: `<base_dir>/_ssh-config-<project_id>:/home/dev/.ssh:z` (read-write)
     - Purpose: If your project uses private git URLs (for example, `git@github.com:...`), provide SSH keys and config here so the container can fetch the repository.

## Expected contents of the optional SSH config directory
- Directory: `<base_dir>/_ssh-config-<project_id>`
- Files:
  - Private/public key pair for the project (for example, `id_ed25519_<project>`, `id_ed25519_<project>.pub`)
  - `config` file with host definitions and `IdentityFile` entries
- Permissions: The directory is mounted read-write to `/home/dev/.ssh` in the container. The init script will use the keys and config directly and, if available, warm up `known_hosts` for `github.com` only when the project's repo is hosted on GitHub.
- Key selection: The init script relies on `SSH_KEY_NAME` if provided in the image/env, but your config file can also refer to the correct `IdentityFile`.

## How to create this directory automatically
- Use the helper command:

```bash
luskctl ssh-init <project_id> [--key-type ed25519|rsa] [--key-name NAME] [--force]
```

- What it does:
  - Resolves the target directory for `<project_id>` as:
    - If `<project>/project.yml` sets `ssh.host_dir`, use it; otherwise
    - `<envs_base>/_ssh-config-<project_id>`
  - Generates an SSH keypair (default: `ed25519`) and writes a default SSH config:
    - A global section applied to all hosts:
      - `Host *`
      - `IdentitiesOnly yes`
      - `StrictHostKeyChecking accept-new`
      - `IdentityFile <generated_private_key>`
      - This prevents interactive host-key prompts (agents are non-interactive) and ensures the same key is used by default for all hosts.
    - A host section for `github.com` with `User git` (inherits `IdentityFile` from `Host *`).
  - The SSH config is rendered from a template. You can provide your own template via `project.yml` -> `ssh.config_template`.
    - Supported tokens in the template: `{{IDENTITY_FILE}}`, `{{KEY_NAME}}`, `{{PROJECT_ID}}`
    - If not provided, a built-in template is used (see `src/luskctl/resources/templates/ssh_config.template`).
  - Prints the resulting paths. Use the `.pub` key to register a deploy key or add it to your Git host.

## SELinux and mount flags
- luskctl uses SELinux mount flags to ensure correct labeling:
  - `:Z` for the workspace mount (container-specific, private labeling)
  - `:z` for all shared directories (shared labeling across containers)

## Git identity configuration
- luskctl automatically configures git author and committer identities inside containers to identify AI-generated commits.
- **Git Author**: Set to the AI agent that created the commit (Codex, Claude, or Mistral Vibe).
- **Git Committer**: Set to human credentials (configurable per project).
- **For CLI mode**: Git identity is set via environment variables in the command aliases for each agent:
  - `codex` -> Author: `Codex <codex@openai.com>`, Committer: human credentials
  - `claude` -> Author: `Claude <noreply@anthropic.com>`, Committer: human credentials
  - `vibe` -> Author: `Mistral Vibe <vibe@mistral.ai>`, Committer: human credentials
  - Each agent's alias sets its own git author, allowing multiple agents to coexist in the same container.
- **For UI mode**: Git identity is set in the entry script based on the default agent (configured via `DEFAULT_AGENT` env var, `default_agent` in config, or `--backend` CLI flag):
  - `codex` -> Author: `Codex <codex@openai.com>`, Committer: human credentials
  - `claude` -> Author: `Claude <noreply@anthropic.com>`, Committer: human credentials
  - `mistral` -> Author: `Mistral Vibe <vibe@mistral.ai>`, Committer: human credentials
  - Unknown backends default to Author: `AI Agent <ai-agent@localhost>`, Committer: human credentials
- **Human credentials configuration** (checked in order):
  1. Per-project: `human_name` and `human_email` in the `git:` section of `project.yml`
  2. Global luskctl config: `human_name` and `human_email` in the `git:` section of `~/.config/luskctl/config.yml`
  3. Global git config: `git config --global user.name` and `git config --global user.email`
  4. Defaults: `Nobody <nobody@localhost>`
- Email addresses for Codex, Claude, and Mistral are GitHub-recognized and will display with avatars in commit history.
- This approach ensures commits show both the AI agent (author) and the human supervisor (committer).

## Quick reference (runtime mounts)
- `/workspace` <- `<state_root>/tasks/<project>/<task>/workspace:Z`
- `/home/dev/.codex` <- `<envs_base>/_codex-config:z`
- `/home/dev/.claude` <- `<envs_base>/_claude-config:z`
- `/home/dev/.vibe` <- `<envs_base>/_vibe-config:z`
- `/home/dev/.blablador` <- `<envs_base>/_blablador-config:z`
- `/home/dev/.config/opencode` <- `<envs_base>/_opencode-config:z`
- `/home/dev/.local/share/opencode` <- `<envs_base>/_opencode-data:z`
- `/home/dev/.local/state` <- `<envs_base>/_opencode-state:z`
- `/home/dev/.ssh` (optional) <- `<envs_base>/_ssh-config-<project>:z`

## How luskctl discovers these paths
- `state_root`: Determined by `LUSKCTL_STATE_DIR` or defaults (root: `/var/lib/luskctl`; user: `${XDG_DATA_HOME:-~/.local/share}/luskctl`).
- `envs_base`: Set in `luskctl-config.yml` under `envs.base_dir`; defaults to `/var/lib/luskctl/envs` if unspecified.

## Minimal setup to run tasks
1. Ensure luskctl can write to the state root (or set `LUSKCTL_STATE_DIR` accordingly).
2. Optionally create the envs base dir (luskctl will create these directories automatically if missing):

```bash
sudo mkdir -p /var/lib/luskctl/envs/_codex-config
sudo mkdir -p /var/lib/luskctl/envs/_claude-config
sudo mkdir -p /var/lib/luskctl/envs/_vibe-config
sudo mkdir -p /var/lib/luskctl/envs/_blablador-config
sudo mkdir -p /var/lib/luskctl/envs/_opencode-config
sudo mkdir -p /var/lib/luskctl/envs/_opencode-data
sudo mkdir -p /var/lib/luskctl/envs/_opencode-state
```

3. If using private git repositories for a project `<proj>`:
   - `sudo mkdir -p /var/lib/luskctl/envs/_ssh-config-<proj>`
   - Place SSH keys and config there (see above). Keys must match your repo host.

## Notes
- The SSH directory is optional. Public HTTPS repos do not require it.
- The `.codex` directory is mounted read-write and should contain any credentials/config required by Codex tooling.
- The `.claude` directory is mounted read-write and should contain any credentials/config required by Claude Code.
- The `.vibe` directory is mounted read-write and should contain any credentials/config required by Mistral Vibe.
- The `.blablador` directory is mounted read-write and should contain any credentials/config required by Blablador (OpenCode).
- Both CLI and UI containers mount the same paths and start with the working directory set to `/workspace`.

## See also
- Run `luskctl config` to see the resolved envs base dir and other important paths.
