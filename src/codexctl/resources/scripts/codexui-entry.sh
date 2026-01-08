#!/usr/bin/env bash
set -euo pipefail

# Reuse SSH + project repo init (if script exists)
if command -v /usr/local/bin/init-ssh-and-repo.sh >/dev/null 2>&1; then
  /usr/local/bin/init-ssh-and-repo.sh || exit $?
fi

# Set git author/committer based on UI backend for AI-generated commits
# This ensures commits made by the UI are properly attributed to the AI agent
if command -v git >/dev/null 2>&1 && [[ -n "${CODEXUI_BACKEND:-}" ]]; then
  case "${CODEXUI_BACKEND,,}" in
    codex)
      git config --global user.name "Codex" || true
      git config --global user.email "codex@openai.com" || true
      ;;
    claude)
      git config --global user.name "Claude" || true
      git config --global user.email "noreply@anthropic.com" || true
      ;;
    mistral)
      git config --global user.name "Mistral Vibe" || true
      git config --global user.email "vibe@mistral.ai" || true
      ;;
    *)
      # Default fallback for unknown backends
      git config --global user.name "AI Agent" || true
      git config --global user.email "ai-agent@localhost" || true
      ;;
  esac
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
ui_entry_js="${CODEXUI_DIR}/server.js"
ui_entry_ts="${CODEXUI_DIR}/server.ts"
ui_entry=""
if [[ -f "${ui_entry_js}" ]]; then
  ui_entry="${ui_entry_js}"
elif [[ -f "${ui_entry_ts}" ]]; then
  ui_entry="${ui_entry_ts}"
else
  echo "!! no UI entrypoint found (expected server.js or server.ts)."
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
# directory is the task workspace. This ensures that server.ts/server.js is
# resolved from CODEXUI_DIR while allowing the UI to treat the workspace as
# its current directory (for project-specific files, etc.).
ui_args=()
if [[ -z "${CODEXUI_LOG:-}" && ! -w /var/log ]]; then
  export CODEXUI_LOG="/tmp/codexui.log"
fi
if [[ "${ui_entry}" == "${ui_entry_js}" ]]; then
  ui_runner="node"
else
  if [[ -x "${CODEXUI_DIR}/node_modules/.bin/tsx" ]]; then
    ui_runner="${CODEXUI_DIR}/node_modules/.bin/tsx"
    if [[ -f "${CODEXUI_DIR}/tsconfig.json" ]]; then
      ui_args+=(--tsconfig "${CODEXUI_DIR}/tsconfig.json")
    fi
  elif [[ -f "${CODEXUI_DIR}/node_modules/ts-node/esm.mjs" ]]; then
    ui_runner="node"
    ui_args+=(--loader "${CODEXUI_DIR}/node_modules/ts-node/esm.mjs")
    if [[ -f "${CODEXUI_DIR}/tsconfig.json" ]]; then
      : "${TS_NODE_PROJECT:=${CODEXUI_DIR}/tsconfig.json}"
      export TS_NODE_PROJECT
    fi
  else
    echo "!! TypeScript entrypoint found but no tsx/ts-node runner is installed."
    exit 1
  fi
fi
echo ">> starting UI on ${HOST}:${PORT} (server: ${ui_entry})"
exec "${ui_runner}" "${ui_args[@]}" "${ui_entry}"
