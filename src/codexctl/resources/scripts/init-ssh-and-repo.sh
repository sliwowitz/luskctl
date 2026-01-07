#!/usr/bin/env bash
set -euo pipefail

# Expected env:
#   SSH_KEY_NAME    - private key name in ~/.ssh (without .pub)
#   REPO_ROOT       - target repo dir (e.g. /workspace/ultimate-container)
#   CODE_REPO       - git URL (https:// or git@)
#   GIT_BRANCH      - optional, e.g. "main" or "master"
#   GIT_RESET_MODE  - "none" (default), "hard", or "soft"
#   CLONE_FROM      - optional alternate source to seed the repo (e.g. file:///git-cache/cache.git)

: "${GIT_RESET_MODE:=none}"

: "${HOME:=/home/dev}"
SSH_DIR="${HOME}/.ssh"

if [[ -n "${SSH_KEY_NAME:-}" ]]; then
  echo ">> SSH: checking ${SSH_KEY_NAME} in ${SSH_DIR}"
  if [[ -f "${SSH_DIR}/${SSH_KEY_NAME}" && -f "${SSH_DIR}/${SSH_KEY_NAME}.pub" && -f "${SSH_DIR}/config" ]]; then
    install -d -m 700 "${SSH_DIR}" || true
    chmod 700 "${SSH_DIR}" || true
    chmod 600 "${SSH_DIR}/${SSH_KEY_NAME}" || true
    chmod 644 "${SSH_DIR}/${SSH_KEY_NAME}.pub" || true
    chmod 644 "${SSH_DIR}/config" || true

    if command -v ssh >/dev/null 2>&1; then
      # Only warm GitHub known_hosts if the project's code repo uses github.com
      if [[ -n "${CODE_REPO:-}" && "${CODE_REPO}" == *"github.com"* ]]; then
        echo '>> warm github known_hosts (best-effort)'
        ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o LogLevel=ERROR git@github.com || true
      fi
    else
      echo 'SSH not installed'
    fi
  else
    echo ">> SSH not fully configured (missing key or config); continuing without SSH"
  fi
fi

if [[ -n "${REPO_ROOT:-}" && -n "${CODE_REPO:-}" ]]; then
  echo ">> syncing repo ${CODE_REPO} -> ${REPO_ROOT}"

  # Make git happy about mounted host-owned dirs
  if command -v git >/dev/null 2>&1; then
    git config --global --add safe.directory "${REPO_ROOT}" || true
  fi

  # New Task Marker Protocol:
  # -------------------------
  # The marker file (.new-task-marker) is created by 'codexctl task new' to signal
  # that this workspace should be reset to the latest remote HEAD. This handles:
  #
  # 1. NEW TASK: Marker exists -> clone or reset to latest HEAD, then remove marker
  # 2. RESTARTED TASK: No marker -> fetch only, preserve local changes
  #
  # This ensures new tasks always start with fresh code while preserving work
  # in progress for restarted containers. It also handles edge cases like stale
  # workspaces from incompletely deleted tasks.
  NEW_TASK_MARKER="${REPO_ROOT}/.new-task-marker"
  IS_NEW_TASK=false
  if [[ -f "${NEW_TASK_MARKER}" ]]; then
    IS_NEW_TASK=true
    echo ">> detected new task marker - will reset to latest HEAD"
  fi

  if [[ ! -d "${REPO_ROOT}/.git" ]]; then
    # No .git directory - perform initial clone
    SRC_REPO="${CLONE_FROM:-${CODE_REPO}}"
    echo ">> initial clone from ${SRC_REPO}"
    git clone --recurse-submodules "${SRC_REPO}" "${REPO_ROOT}"
    # If we cloned from a cache, repoint origin to the canonical repo for future updates
    if [[ -n "${CLONE_FROM:-}" && "${CLONE_FROM}" != "${CODE_REPO}" ]]; then
      git -C "${REPO_ROOT}" remote set-url origin "${CODE_REPO}" || true
      git -C "${REPO_ROOT}" remote set-url --push origin "${CODE_REPO}" || true
      # Fetch latest from upstream to ensure we have all refs
      git -C "${REPO_ROOT}" fetch --all --prune || true
    fi
    # Remove marker after successful clone (new task is now initialized)
    rm -f "${NEW_TASK_MARKER}" 2>/dev/null || true

  elif [[ "${IS_NEW_TASK}" == "true" ]]; then
    # .git exists but this is a new task (marker present)
    # This happens when a previous task with the same ID wasn't fully cleaned up.
    # Reset to latest remote HEAD to ensure fresh state.
    echo ">> new task with existing .git - resetting to latest HEAD"
    git -C "${REPO_ROOT}" fetch --all --prune
    TARGET_BRANCH="${GIT_BRANCH:-main}"
    echo ">> git reset --hard origin/${TARGET_BRANCH}"
    reset_ok=true
    if ! git -C "${REPO_ROOT}" reset --hard "origin/${TARGET_BRANCH}"; then
      echo ">> WARNING: git reset failed; preserving new task marker for retry"
      reset_ok=false
    fi
    git -C "${REPO_ROOT}" clean -fd || true
    # Remove marker only after successful reset
    if [[ "${reset_ok}" == "true" ]]; then
      rm -f "${NEW_TASK_MARKER}" 2>/dev/null || true
    fi

  else
    # .git exists and no marker - this is a restarted task
    # Only fetch updates, preserve local changes
    echo ">> restarted task - fetching updates (preserving local changes)"
    git -C "${REPO_ROOT}" fetch --all --prune
    # Only reset if explicitly requested via GIT_RESET_MODE
    if [[ -n "${GIT_BRANCH:-}" && "${GIT_RESET_MODE}" != "none" ]]; then
      echo ">> git reset (${GIT_RESET_MODE}) to origin/${GIT_BRANCH}"
      case "${GIT_RESET_MODE}" in
        hard)
          git -C "${REPO_ROOT}" reset --hard "origin/${GIT_BRANCH}" || true
          ;;
        soft)
          git -C "${REPO_ROOT}" reset "origin/${GIT_BRANCH}" || true
          ;;
      esac
    fi
  fi
fi

# Optional toolchain introspection
if command -v gcc >/dev/null 2>&1; then
  echo "gcc: $(gcc --version | head -1)"
fi
if command -v gfortran >/dev/null 2>&1; then
  echo "gfortran: $(gfortran --version | head -1)"
fi
if command -v cmake >/dev/null 2>&1; then
  echo "cmake: $(cmake --version | head -1)"
fi
if command -v clang-format-20 >/dev/null 2>&1; then
  echo "clang-format: $(clang-format-20 --version)"
fi
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi:"
  nvidia-smi || true
fi
if command -v nvcc >/dev/null 2>&1; then
  echo "nvcc:"
  nvcc --version || true
fi
if command -v nvc >/dev/null 2>&1; then
  echo "nvc:"
  nvc --version || true
fi
if command -v nvfortran >/dev/null 2>&1; then
  echo "nvfortran:"
  nvfortran --version || true
fi

# Signal readiness for host tools that watch initial logs
echo ">> init complete"
exec bash
