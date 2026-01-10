#!/usr/bin/env bash
set -euo pipefail

# Reuse SSH + project repo init (if script exists)
if command -v /usr/local/bin/init-ssh-and-repo.sh >/dev/null 2>&1; then
  /usr/local/bin/init-ssh-and-repo.sh || exit $?
fi

# Set git author/committer based on UI backend for AI-generated commits
# Author = AI agent, Committer = Human (if configured)
# This ensures commits made by the UI are properly attributed
if command -v git >/dev/null 2>&1 && [[ -n "${CODEXUI_BACKEND:-}" ]]; then
  case "${CODEXUI_BACKEND,,}" in
    codex)
      export GIT_AUTHOR_NAME="Codex"
      export GIT_AUTHOR_EMAIL="codex@openai.com"
      ;;
    claude)
      export GIT_AUTHOR_NAME="Claude"
      export GIT_AUTHOR_EMAIL="noreply@anthropic.com"
      ;;
    mistral)
      export GIT_AUTHOR_NAME="Mistral Vibe"
      export GIT_AUTHOR_EMAIL="vibe@mistral.ai"
      ;;
    *)
      # Default fallback for unknown backends
      export GIT_AUTHOR_NAME="AI Agent"
      export GIT_AUTHOR_EMAIL="ai-agent@localhost"
      ;;
  esac
  
  # Set committer to human credentials
  export GIT_COMMITTER_NAME="${HUMAN_GIT_NAME:-Nobody}"
  export GIT_COMMITTER_EMAIL="${HUMAN_GIT_EMAIL:-nobody@localhost}"
fi

: "${CODEXUI_DIR:=/opt/codexui}"
: "${CODEXUI_DIST_TAG:=v0.0.0}"
: "${CODEXUI_DIST_URL:=https://github.com/sliwowitz/codex-in-podman/releases/download/${CODEXUI_DIST_TAG}/codexui-dist.tar.gz}"
: "${HOST:=0.0.0.0}"
: "${PORT:=7860}"

echo ">> fetching CodexUI release asset ${CODEXUI_DIST_URL}"
mkdir -p "${CODEXUI_DIR}"
tarball_path="/tmp/codexui-dist.tar.gz"
curl -fsSL "${CODEXUI_DIST_URL}" -o "${tarball_path}"

# Validate that the download succeeded and the archive is usable
if [[ ! -s "${tarball_path}" ]]; then
  echo "!! failed to download CodexUI distribution (file is missing or empty): ${tarball_path}"
  exit 1
fi

if ! tar -tzf "${tarball_path}" >/dev/null 2>&1; then
  echo "!! downloaded CodexUI archive appears to be corrupted or not a valid tar.gz: ${tarball_path}"
  exit 1
fi

tar -xzf "${tarball_path}" -C "${CODEXUI_DIR}"
rm -f "${tarball_path}"
cd "${CODEXUI_DIR}"
ui_entry="${CODEXUI_DIR}/dist/server.js"
if [[ ! -f "${ui_entry}" ]]; then
  echo "!! no UI entrypoint found (expected dist/server.js)."
  exit 1
fi

# If a task workspace repository exists, prefer that as working directory
if [[ -n "${REPO_ROOT:-}" && -d "${REPO_ROOT}" ]]; then
  echo ">> switching to repo root: ${REPO_ROOT}"
  cd "${REPO_ROOT}"
fi

# Always run the UI server from the CodexUI repo, even if the working
# directory is the task workspace. This ensures that dist/server.js is
# resolved from CODEXUI_DIR while allowing the UI to treat the workspace as
# its current directory (for project-specific files, etc.).
if [[ -z "${CODEXUI_LOG:-}" && ! -w /var/log ]]; then
  export CODEXUI_LOG="/tmp/codexui.log"
fi
echo ">> starting UI on ${HOST}:${PORT}"
exec node "${ui_entry}"
