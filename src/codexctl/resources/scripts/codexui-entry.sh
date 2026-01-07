#!/usr/bin/env bash
set -euo pipefail

# Reuse SSH + project repo init (if script exists)
if command -v /usr/local/bin/init-ssh-and-repo.sh >/dev/null 2>&1; then
  /usr/local/bin/init-ssh-and-repo.sh || exit $?
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
if [[ ! -f "${ui_entry_ts}" ]]; then
  echo "!! no UI entrypoint found (expected server.ts)."
  exit 1
fi

echo ">> npm install (include dev for TypeScript)"
if [[ -f package-lock.json || -f npm-shrinkwrap.json ]]; then
  npm ci --no-fund --no-audit --progress=false
else
  npm install --no-fund --no-audit --progress=false
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
ui_args=()
if [[ -x "${CODEXUI_DIR}/node_modules/.bin/tsx" ]]; then
  ui_runner="${CODEXUI_DIR}/node_modules/.bin/tsx"
elif [[ -x "${CODEXUI_DIR}/node_modules/.bin/ts-node" ]]; then
  ui_runner="${CODEXUI_DIR}/node_modules/.bin/ts-node"
  ui_args+=(--esm)
  if [[ -f "${CODEXUI_DIR}/tsconfig.json" ]]; then
    ui_args+=(--project "${CODEXUI_DIR}/tsconfig.json")
  fi
else
  echo "!! TypeScript entrypoint found but no tsx/ts-node runner is installed."
  exit 1
fi
echo ">> starting UI on ${HOST}:${PORT} (server: ${ui_entry_ts})"
exec "${ui_runner}" "${ui_args[@]}" "${ui_entry_ts}"
