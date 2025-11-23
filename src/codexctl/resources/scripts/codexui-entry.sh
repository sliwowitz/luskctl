#!/usr/bin/env bash
set -euo pipefail

# Reuse SSH + project repo init (if script exists)
if command -v init-ssh-and-repo.sh >/dev/null 2>&1; then
  init-ssh-and-repo.sh || exit $?
fi

: "${CODEXUI_DIR:=/opt/codexui}"
: "${CODEXUI_REPO:=https://github.com/sliwowitz/codex-in-podman.git}"
: "${HOST:=0.0.0.0}"
: "${PORT:=7860}"

echo ">> syncing CodexUI repo ${CODEXUI_REPO} -> ${CODEXUI_DIR}"
if [[ ! -d "${CODEXUI_DIR}/.git" ]]; then
  git clone --depth=1 "${CODEXUI_REPO}" "${CODEXUI_DIR}"
else
  git -C "${CODEXUI_DIR}" fetch --all --prune
  git -C "${CODEXUI_DIR}" reset --hard origin/main || git -C "${CODEXUI_DIR}" reset --hard origin/master
fi

echo ">> npm install (omit dev)"
cd "${CODEXUI_DIR}"
if [[ -f package-lock.json || -f npm-shrinkwrap.json ]]; then
  npm ci --omit=dev --no-fund --no-audit --progress=false
else
  npm install --omit=dev --no-fund --no-audit --progress=false
fi

# If a task workspace repository exists, prefer that as working directory
if [[ -n "${REPO_ROOT:-}" && -d "${REPO_ROOT}" ]]; then
  echo ">> switching to repo root: ${REPO_ROOT}"
  cd "${REPO_ROOT}"
fi

# Always run the UI server from the CodexUI repo, even if the working
# directory is the task workspace. This ensures that server.js is resolved
# from CODEXUI_DIR while allowing the UI to treat the workspace as its
# current directory (for project-specific files, etc.).
echo ">> starting UI on ${HOST}:${PORT} (server: ${CODEXUI_DIR}/server.js)"
exec node "${CODEXUI_DIR}/server.js"
