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

cd "${CODEXUI_DIR}"
ui_entry_ts="${CODEXUI_DIR}/server.ts"
ui_entry_js="${CODEXUI_DIR}/server.js"
install_dev=0
if [[ -f "${ui_entry_ts}" ]]; then
  install_dev=1
fi

if [[ "${install_dev}" -eq 1 ]]; then
  echo ">> npm install (include dev for TypeScript)"
else
  echo ">> npm install (omit dev)"
fi
if [[ -f package-lock.json || -f npm-shrinkwrap.json ]]; then
  if [[ "${install_dev}" -eq 1 ]]; then
    npm ci --no-fund --no-audit --progress=false
  else
    npm ci --omit=dev --no-fund --no-audit --progress=false
  fi
else
  if [[ "${install_dev}" -eq 1 ]]; then
    npm install --no-fund --no-audit --progress=false
  else
    npm install --omit=dev --no-fund --no-audit --progress=false
  fi
fi

# If a task workspace repository exists, prefer that as working directory
if [[ -n "${REPO_ROOT:-}" && -d "${REPO_ROOT}" ]]; then
  echo ">> switching to repo root: ${REPO_ROOT}"
  cd "${REPO_ROOT}"
fi

# Always run the UI server from the CodexUI repo, even if the working
# directory is the task workspace. This ensures that server.ts is resolved
# from CODEXUI_DIR while allowing the UI to treat the workspace as its
# current directory (for project-specific files, etc.).
if [[ -f "${ui_entry_ts}" ]]; then
  if [[ -x "${CODEXUI_DIR}/node_modules/.bin/tsx" ]]; then
    ui_runner="${CODEXUI_DIR}/node_modules/.bin/tsx"
  elif [[ -x "${CODEXUI_DIR}/node_modules/.bin/ts-node" ]]; then
    ui_runner="${CODEXUI_DIR}/node_modules/.bin/ts-node"
  else
    echo "!! TypeScript entrypoint found but no tsx/ts-node runner is installed."
    exit 1
  fi
  echo ">> starting UI on ${HOST}:${PORT} (server: ${ui_entry_ts})"
  exec "${ui_runner}" "${ui_entry_ts}"
elif [[ -f "${ui_entry_js}" ]]; then
  echo ">> starting UI on ${HOST}:${PORT} (server: ${ui_entry_js})"
  exec node "${ui_entry_js}"
else
  echo "!! no UI entrypoint found (expected server.ts or server.js)."
  exit 1
fi
