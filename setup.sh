#!/usr/bin/env bash
set -euo pipefail

SETUP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SETUP_WITH_DOCKER=0
SETUP_PULL_LFS=1
SETUP_INSTALL_DEV=1
SETUP_DOCKER_LOGIN_REQUIRED=0
SETUP_TEMP_DIR=""

usage() {
  cat <<'EOF'
Usage: ./setup.sh [options]

Prepare Maker's Supply Archive on Ubuntu, Debian, Arch Linux, or Fedora.

The default setup installs the system prerequisites, Git LFS, uv, Python 3.12,
the project and development dependencies, then downloads and validates the LFS
archive. It is safe to run this script again.

Options:
  --with-docker     Also install and start Docker for the visual catalog
  --skip-lfs-pull   Do not download the approximately 4.1 GiB LFS archive
  --runtime-only    Skip lint, type-check, and test dependencies
  -h, --help        Show this help
EOF
}

log() {
  printf '\n==> %s\n' "$*"
}

die() {
  printf 'setup: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if [[ -n "$SETUP_TEMP_DIR" && -d "$SETUP_TEMP_DIR" ]]; then
    rm -rf -- "$SETUP_TEMP_DIR"
  fi
}
trap cleanup EXIT

while (($#)); do
  case "$1" in
    --with-docker)
      SETUP_WITH_DOCKER=1
      ;;
    --skip-lfs-pull)
      SETUP_PULL_LFS=0
      ;;
    --runtime-only)
      SETUP_INSTALL_DEV=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'setup: unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

[[ "$(uname -s)" == "Linux" ]] || die "this setup script currently supports Linux only"
[[ -f /etc/os-release ]] || die "cannot identify this Linux distribution"

# shellcheck disable=SC1091
. /etc/os-release
SETUP_OS_ID="${ID:-unknown}"
SETUP_OS_FAMILY="${ID_LIKE:-}"

case " $SETUP_OS_ID $SETUP_OS_FAMILY " in
  *" ubuntu "*|*" debian "*)
    SETUP_PACKAGE_MANAGER=apt
    ;;
  *" arch "*)
    SETUP_PACKAGE_MANAGER=pacman
    ;;
  *" fedora "*)
    SETUP_PACKAGE_MANAGER=dnf
    ;;
  *)
    die "unsupported distribution '$SETUP_OS_ID' (supported: Ubuntu, Debian, Arch, Fedora)"
    ;;
esac

SETUP_PRIVILEGE=()
if ((EUID != 0)); then
  if command -v sudo >/dev/null 2>&1; then
    SETUP_PRIVILEGE=(sudo)
  fi
fi

as_root() {
  if ((EUID != 0)) && ((${#SETUP_PRIVILEGE[@]} == 0)); then
    die "sudo is required to install system packages"
  fi
  "${SETUP_PRIVILEGE[@]}" "$@"
}

install_packages() {
  local packages=("$@")
  ((${#packages[@]})) || return 0

  case "$SETUP_PACKAGE_MANAGER" in
    apt)
      as_root apt-get update
      as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        "${packages[@]}"
      ;;
    dnf)
      as_root dnf install -y "${packages[@]}"
      ;;
    pacman)
      # Arch does not support partial upgrades, so refresh and upgrade together.
      as_root pacman -Syu --needed --noconfirm "${packages[@]}"
      ;;
  esac
}

log "Detected ${PRETTY_NAME:-$SETUP_OS_ID} ($SETUP_PACKAGE_MANAGER)"
case "$SETUP_PACKAGE_MANAGER" in
  apt) command -v apt-get >/dev/null 2>&1 || die "apt-get is unavailable" ;;
  dnf) command -v dnf >/dev/null 2>&1 || die "dnf is unavailable" ;;
  pacman) command -v pacman >/dev/null 2>&1 || die "pacman is unavailable" ;;
esac

SETUP_BASE_MISSING=0
for SETUP_COMMAND in git git-lfs curl openssl; do
  if ! command -v "$SETUP_COMMAND" >/dev/null 2>&1; then
    SETUP_BASE_MISSING=1
    break
  fi
done

if ((SETUP_BASE_MISSING)); then
  log "Installing Git, Git LFS, curl, certificates, and OpenSSL"
  install_packages git git-lfs curl ca-certificates openssl
else
  log "System prerequisites are already installed"
fi

for SETUP_COMMAND in git git-lfs curl; do
  command -v "$SETUP_COMMAND" >/dev/null 2>&1 || \
    die "$SETUP_COMMAND is still unavailable after package installation"
done

SETUP_UV="$(command -v uv || true)"
if [[ -z "$SETUP_UV" ]]; then
  log "Installing uv"
  SETUP_TEMP_DIR="$(mktemp -d)"
  curl --proto '=https' --tlsv1.2 -fsSL \
    https://astral.sh/uv/install.sh -o "$SETUP_TEMP_DIR/install-uv.sh"
  sh "$SETUP_TEMP_DIR/install-uv.sh"

  for SETUP_UV_CANDIDATE in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [[ -x "$SETUP_UV_CANDIDATE" ]]; then
      SETUP_UV="$SETUP_UV_CANDIDATE"
      break
    fi
  done
  [[ -n "$SETUP_UV" ]] || die "uv installed but its executable could not be found"
else
  log "uv is already installed ($("$SETUP_UV" --version))"
fi

cd "$SETUP_DIR"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || \
  die "$SETUP_DIR is not a Git checkout"

log "Initializing Git LFS for this checkout"
git lfs install --local
if ((SETUP_PULL_LFS)); then
  log "Downloading the LFS archive (approximately 4.1 GiB)"
  git lfs pull
else
  log "Skipping the LFS download as requested"
fi

log "Installing Python 3.12 and project dependencies"
"$SETUP_UV" python install 3.12
SETUP_SYNC_ARGS=(sync --frozen --python 3.12 --all-packages)
if ((SETUP_INSTALL_DEV)); then
  SETUP_SYNC_ARGS+=(--extra dev)
fi
"$SETUP_UV" "${SETUP_SYNC_ARGS[@]}"

log "Validating the checkout"
if ((SETUP_PULL_LFS)); then
  "$SETUP_UV" run makers-supply validate
  "$SETUP_UV" run makers-supply lfs-preflight
else
  "$SETUP_UV" run makers-supply validate --no-check-blobs
fi

if ((SETUP_WITH_DOCKER)); then
  if ! command -v docker >/dev/null 2>&1; then
    log "Installing Docker"
    case "$SETUP_PACKAGE_MANAGER" in
      apt) install_packages docker.io ;;
      dnf) install_packages moby-engine ;;
      pacman) install_packages docker ;;
    esac
  else
    log "Docker is already installed ($(docker --version))"
  fi

  if ! docker info >/dev/null 2>&1 && command -v systemctl >/dev/null 2>&1; then
    log "Enabling and starting Docker"
    as_root systemctl enable --now docker
  fi

  if ! docker info >/dev/null 2>&1 && ((EUID != 0)); then
    SETUP_USER="$(id -un)"
    if id -nG | tr ' ' '\n' | grep -qx docker; then
      die "Docker is installed but its daemon is unavailable; inspect 'systemctl status docker'"
    fi
    if ! id -nG "$SETUP_USER" | tr ' ' '\n' | grep -qx docker; then
      log "Granting $SETUP_USER access to Docker"
      as_root usermod -aG docker "$SETUP_USER"
    fi
    SETUP_DOCKER_LOGIN_REQUIRED=1
  elif ! docker info >/dev/null 2>&1; then
    die "Docker is installed but its daemon is unavailable; inspect 'systemctl status docker'"
  fi
fi

printf '\nSetup complete. Try:\n  uv run makers-supply --help\n'
if ((SETUP_WITH_DOCKER)); then
  if ((SETUP_DOCKER_LOGIN_REQUIRED)); then
    printf '\nLog out and back in once to activate Docker group membership, then run:\n'
  else
    printf '\nRun the visual catalog with:\n'
  fi
  printf '  ./scripts/run-catalog-web.sh\n'
fi
