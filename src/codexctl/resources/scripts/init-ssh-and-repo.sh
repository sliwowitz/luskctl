#!/usr/bin/env bash
set -euo pipefail

# Expected env:
#   SSH_KEY_NAME    - private key name in /tmp/.ssh-config (without .pub)
#   REPO_ROOT       - target repo dir (e.g. /workspace/ultimate-container)
#   CODE_REPO       - git URL (https:// or git@)
#   GIT_BRANCH      - optional, e.g. "main" or "master"
#   GIT_RESET_MODE  - "none" (default), "hard", or "soft"
#   CLONE_FROM      - optional alternate source to seed the repo (e.g. file:///git-cache/cache.git)

: "${GIT_RESET_MODE:=none}"

SSH_DIR=/tmp/.ssh-config

if [[ -n "${SSH_KEY_NAME:-}" ]]; then
  echo ">> SSH: checking ${SSH_KEY_NAME} in ${SSH_DIR}"
  if [[ -f "${SSH_DIR}/${SSH_KEY_NAME}" && -f "${SSH_DIR}/${SSH_KEY_NAME}.pub" && -f "${SSH_DIR}/config" ]]; then
    install -d -m 700 /root/.ssh
    cp -f "${SSH_DIR}/${SSH_KEY_NAME}" /root/.ssh/
    chmod 600 "/root/.ssh/${SSH_KEY_NAME}"
    cp -f "${SSH_DIR}/${SSH_KEY_NAME}.pub" /root/.ssh/
    chmod 644 "/root/.ssh/${SSH_KEY_NAME}.pub"
    cp -f "${SSH_DIR}/config" /root/.ssh/config
    chmod 644 /root/.ssh/config

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

  if [[ ! -d "${REPO_ROOT}/.git" ]]; then
    SRC_REPO="${CLONE_FROM:-${CODE_REPO}}"
    echo ">> initial clone from ${SRC_REPO}"
    git clone --recurse-submodules "${SRC_REPO}" "${REPO_ROOT}"
    # If we cloned from a cache, repoint origin to the canonical repo for future updates
    if [[ -n "${CLONE_FROM:-}" && "${CLONE_FROM}" != "${CODE_REPO}" ]]; then
      git -C "${REPO_ROOT}" remote set-url origin "${CODE_REPO}" || true
      git -C "${REPO_ROOT}" remote set-url --push origin "${CODE_REPO}" || true
      # Optionally fetch latest from upstream right away
      git -C "${REPO_ROOT}" fetch --all --prune || true
    fi
  else
    git -C "${REPO_ROOT}" fetch --all --prune
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
