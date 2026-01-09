# Git Gate and Security Modes

This document describes the **Git gate** concept and the distinction between **online** and **gatekeeping** projects.

## Update (January 2026)

### Terminology change: Cache → Gate

The "cache" has been renamed to "gate" throughout the codebase because it serves as more than just a cache - it's the central gatekeeping mechanism for controlling code flow:

- `codexctl cache-init` → `codexctl gate-init`
- `cache_path` → `gate_path`
- `/git-cache/cache.git` → `/git-gate/gate.git`
- Config section `cache:` → `gate:`

### New Features

1. **External remote exposure** (`gatekeeping.expose_external_remote`):
   - Optionally add upstream URL as "external" remote in container
   - Container can see URL but cannot fetch/push (no credentials/network)
   - Useful for IDE integration on the host side

2. **Upstream polling** (`gatekeeping.upstream_polling`):
   - TUI periodically checks if upstream has new commits using `git ls-remote` (cheap)
   - Shows notification when gate is behind upstream
   - Configurable interval (default: 5 minutes)

3. **Auto-sync** (`gatekeeping.auto_sync`):
   - Automatically sync gate when upstream changes detected
   - Configure specific branches to auto-sync
   - Opt-in (default: disabled)

4. **Container staleness warning**:
   - When `expose_external_remote: true`, container init checks if gate is behind upstream
   - Shows informational message with commit counts

---

## Concept: Git gate + two security modes

### 1. Three layers: upstream → gate → tasks

For each project you conceptually have three Git layers:

1. **Upstream (real remote)**
   * The canonical repo: GitHub, GitLab, internal Git server, etc.
   * Example: `git@github.com:org/repo.git`

2. **Local gate (host-side)**
   * A mirror of the upstream, stored under the project's state directory:
     * `STATE_ROOT/gate/<project_id>.git`
   * Purpose:
     * Speed up **clone** operations (no repeated large network transfers).
     * In gatekeeping setups, act as the **only thing** containers can access.
     * Serve as a communication channel between host and container.

3. **Task working copy (container)**
   * A regular Git working directory underneath each task's workspace.
   * Each **task** gets its own **isolated repo**, seeded from either:
     * the real upstream (online mode), or
     * the local gate (gatekeeping mode).

---

### 2. Online vs Gatekept projects

The project's **security mode** controls how tasks interact with upstream vs gate:

#### Online projects

* **Goal:** the agent behaves like a normal developer:
  * It can push branches directly to upstream (subject to repo permissions).
  * It can use `gh` or other GitHub/GitLab tooling normally.
* Typical behaviour:
  * `CODE_REPO` inside the container points to the **upstream URL**.
  * If a local gate exists, the container will seed the initial clone from it (`CLONE_FROM=file:///git-gate/gate.git`) and then repoint `origin` to upstream.
  * The gate is a performance accelerator in online mode; security comes from normal upstream auth.

#### Gatekept projects

* **Goal:** agent's changes must **not** reach the canonical repo directly.
  * Tasks only interact with a host-side gate mirror (no direct upstream access inside the container).
  * Humans (or other reviewing agents) can promote changes from the gate to upstream.
* Typical behaviour:
  * Host maintains a mirror clone under the project's gate path.
  * Container sees only this gate mirror as `CODE_REPO`:
    * `CODE_REPO=file:///git-gate/gate.git`
  * Container **never sees** upstream URLs, nor any upstream credentials (unless relaxed mode).

* **Optional SSH mount** (`ssh.mount_in_gatekeeping`):
  * By default, containers in gatekeeping mode have no SSH access.
  * Set `ssh.mount_in_gatekeeping: true` in project.yml to mount SSH credentials while still enforcing the gate-only model for the main repository.
  * This is useful for repos with git submodules that need to be fetched from private repositories.
  * The user should ensure the SSH key does not have write access to upstream repositories.

* **Optional external remote exposure** (`gatekeeping.expose_external_remote`):
  * By default, containers in gatekeeping mode have no knowledge of the upstream URL.
  * Set `gatekeeping.expose_external_remote: true` in project.yml to add the upstream URL as a remote named "external" in the container's git config.
  * The container can see this URL but cannot actually fetch from or push to it (no network access or credentials by default).
  * This is a "relaxed gatekeeping" mode - if you also provide network access, the container can read from upstream.
  * Useful for IDE integration on the host side.

* **Upstream polling** (`gatekeeping.upstream_polling`):
  * TUI can periodically check if upstream has new commits.
  * Uses `git ls-remote` which only queries refs (cheap, no object download).
  * Shows notification in TUI when gate is behind upstream.
  * Configuration:
    ```yaml
    gatekeeping:
      upstream_polling:
        enabled: true           # default: true
        interval_minutes: 5     # default: 5
    ```

* **Auto-sync** (`gatekeeping.auto_sync`):
  * When enabled, automatically sync gate branches when upstream changes detected.
  * Opt-in feature (default: disabled) to preserve explicit human control.
  * Configuration:
    ```yaml
    gatekeeping:
      auto_sync:
        enabled: false
        branches:
          - main
          - dev
    ```

### Host-side gate lifecycle

1. Generate SSH material for private upstreams (optional for public HTTPS):
   - `codexctl ssh-init <project>`
2. Initialize or update the gate mirror:
   - `codexctl gate-init <project>` (use `--force` to recreate)
3. Run tasks:
   - Online: container clones from gate then talks to upstream directly.
   - Gatekept: container talks only to the gate mirror.

---

## Configuration Example

```yaml
project:
  id: "myproject"
  security_class: "gatekeeping"

git:
  upstream_url: "git@github.com:org/repo.git"
  default_branch: "main"

ssh:
  key_name: "id_ed25519_myproject"
  # mount_in_gatekeeping: true  # Enable SSH in gatekeeping mode

gatekeeping:
  # Expose upstream URL as "external" remote (relaxed gatekeeping)
  expose_external_remote: true

  # TUI polls upstream for changes
  upstream_polling:
    enabled: true
    interval_minutes: 5

  # Automatically sync gate when upstream changes
  auto_sync:
    enabled: false
    branches:
      - main
```

---

## Mental model

* **Online**:
  * containers trust the real upstream,
  * gate is a performance optimization.

* **Gatekept**:
  * containers trust only host-local gate mirror,
  * real upstream is "air-gapped" behind human review,
  * gate serves as communication channel between host IDE and container.

* **Relaxed Gatekept** (`expose_external_remote: true`):
  * containers know the upstream URL but default to no access,
  * if network is available, can read from upstream (not write),
  * useful for IDE integration and staleness awareness.
