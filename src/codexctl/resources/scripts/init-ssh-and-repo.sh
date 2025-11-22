#!/usr/bin/env bash
set -euo pipefail

# Expected env:
#   SSH_KEY_NAME    - private key name in /home/dev/.ssh (without .pub)
#   REPO_ROOT       - target repo dir (e.g. /workspace/ultimate-container)
#   CODE_REPO       - git URL (https:// or git@)
#   GIT_BRANCH      - optional, e.g. "main" or "master"
#   GIT_RESET_MODE  - "none" (default), "hard", or "soft"

: "${GIT_RESET_MODE:=none}"

SSH_DIR=/home/dev/.ssh

if [[ -n "${SSH_KEY_NAME:-}" ]]; then
  echo ">> SSH: verifying ${SSH_KEY_NAME} in ${SSH_DIR}"
  test -f "${SSH_DIR}/${SSH_KEY_NAME}"       || { echo "missing ${SSH_KEY_NAME}"; exit 1; }
  test -f "${SSH_DIR}/${SSH_KEY_NAME}.pub"   || { echo "missing ${SSH_KEY_NAME}.pub"; exit 1; }
  test -f "${SSH_DIR}/config"                || { echo 'missing .ssh/config'; exit 1; }

  install -d -m 700 /root/.ssh
  cp -f "${SSH_DIR}/${SSH_KEY_NAME}" /root/.ssh/
  chmod 600 "/root/.ssh/${SSH_KEY_NAME}"
  cp -f "${SSH_DIR}/${SSH_KEY_NAME}.pub" /root/.ssh/
  chmod 644 "/root/.ssh/${SSH_KEY_NAME}.pub"
  cp -f "${SSH_DIR}/config" /root/.ssh/config
  chmod 644 /root/.ssh/config

  if command -v ssh >/dev/null 2>&1; then
    echo '>> warm github known_hosts (best-effort)'
    ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o LogLevel=ERROR git@github.com || true
  else
    echo 'SSH not installed'
  fi
fi

if [[ -n "${REPO_ROOT:-}" && -n "${CODE_REPO:-}" ]]; then
  echo ">> syncing repo ${CODE_REPO} -> ${REPO_ROOT}"

  # Make git happy about mounted host-owned dirs
  if command -v git >/dev/null 2>&1; then
    git config --global --add safe.directory "${REPO_ROOT}" || true
  fi

  if [[ ! -d "${REPO_ROOT}/.git" ]]; then
    git clone --recurse-submodules "${CODE_REPO}" "${REPO_ROOT}"
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
