#!/usr/bin/env bash
set -euo pipefail

CATALOG_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CATALOG_ROOT="$(cd -- "$CATALOG_SCRIPT_DIR/.." && pwd)"
CATALOG_IMAGE="${MAKERS_SUPPLY_IMAGE:-makers-supply-catalog:local}"
CATALOG_CONTAINER="${MAKERS_SUPPLY_CONTAINER_NAME:-makers-supply-ui}"
CATALOG_STATE_VOLUME="${MAKERS_SUPPLY_STATE_VOLUME:-makers-supply-catalog-state}"
CATALOG_ADMIN="${MAKERS_SUPPLY_ADMIN:-admin}"
CATALOG_PORT="${MAKERS_SUPPLY_PORT:-8000}"
CATALOG_BUILD_IMAGE=1
CATALOG_DETACH=0

usage() {
  cat <<'EOF'
Usage: ./scripts/run-catalog-web.sh [options]

Build the catalog SQLite database and run the visual catalog on localhost.

Options:
  --port PORT    Bind to 127.0.0.1:PORT (default: 8000)
  --detach       Run in the background
  --no-build     Reuse the existing local Docker image
  -h, --help     Show this help

Environment overrides:
  MAKERS_SUPPLY_ADMIN                 Initial administrator name (default: admin)
  MAKERS_SUPPLY_ADMIN_PASSWORD_STDIN  Set to 1 to read the first password from stdin
  MAKERS_SUPPLY_IMAGE                 Docker image tag
  MAKERS_SUPPLY_CONTAINER_NAME        Docker container name
  MAKERS_SUPPLY_STATE_VOLUME          Docker volume for accounts and lists
  MAKERS_SUPPLY_SECRET_KEY            Override the persisted local session secret
EOF
}

while (($#)); do
  case "$1" in
    --port)
      if (($# < 2)); then
        echo "--port requires a value" >&2
        exit 2
      fi
      CATALOG_PORT="$2"
      shift 2
      ;;
    --detach)
      CATALOG_DETACH=1
      shift
      ;;
    --no-build)
      CATALOG_BUILD_IMAGE=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! "$CATALOG_PORT" =~ ^[0-9]+$ ]] || ((CATALOG_PORT < 1 || CATALOG_PORT > 65535)); then
  echo "port must be an integer between 1 and 65535" >&2
  exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Run ./setup.sh --with-docker first." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Cannot access the Docker daemon. Start Docker and refresh your docker-group login." >&2
  exit 1
fi

mkdir -p "$CATALOG_ROOT/.state" "$CATALOG_ROOT/dist"
chmod 0700 "$CATALOG_ROOT/.state"
CATALOG_SECRET_FILE="$CATALOG_ROOT/.state/catalog-web.secret"
if [[ -n "${MAKERS_SUPPLY_SECRET_KEY:-}" ]]; then
  CATALOG_SECRET="$MAKERS_SUPPLY_SECRET_KEY"
else
  if [[ ! -s "$CATALOG_SECRET_FILE" ]]; then
    umask 077
    if command -v openssl >/dev/null 2>&1; then
      openssl rand -hex 32 >"$CATALOG_SECRET_FILE"
    elif command -v python3 >/dev/null 2>&1; then
      python3 -c 'import secrets; print(secrets.token_hex(32))' >"$CATALOG_SECRET_FILE"
    else
      echo "OpenSSL or Python 3 is required to create the local session secret." >&2
      exit 1
    fi
  fi
  chmod 0600 "$CATALOG_SECRET_FILE"
  IFS= read -r CATALOG_SECRET <"$CATALOG_SECRET_FILE"
fi
if ((${#CATALOG_SECRET} < 32)); then
  echo "MAKERS_SUPPLY_SECRET_KEY must contain at least 32 characters." >&2
  exit 1
fi

cd "$CATALOG_ROOT"
if ((CATALOG_BUILD_IMAGE)); then
  echo "Building $CATALOG_IMAGE ..."
  docker build -t "$CATALOG_IMAGE" -f apps/catalog-web/Dockerfile .
elif ! docker image inspect "$CATALOG_IMAGE" >/dev/null 2>&1; then
  echo "Docker image $CATALOG_IMAGE does not exist; remove --no-build." >&2
  exit 1
fi

echo "Generating dist/makers-supply.sqlite ..."
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --workdir /archive \
  -e MAKERS_SUPPLY_ROOT=/archive \
  -v "$CATALOG_ROOT:/archive" \
  "$CATALOG_IMAGE" \
  makers-supply build-db --root /archive --output /archive/dist/makers-supply.sqlite

docker volume create "$CATALOG_STATE_VOLUME" >/dev/null
CATALOG_ADMIN_TTY=(-i)
if [[ -t 0 && -t 1 && "${MAKERS_SUPPLY_ADMIN_PASSWORD_STDIN:-0}" != "1" ]]; then
  CATALOG_ADMIN_TTY+=(-t)
fi
CATALOG_ADMIN_OPTIONS=(--if-missing)
if [[ "${MAKERS_SUPPLY_ADMIN_PASSWORD_STDIN:-0}" == "1" ]]; then
  CATALOG_ADMIN_OPTIONS+=(--password-stdin)
fi
docker run --rm "${CATALOG_ADMIN_TTY[@]}" \
  -e MAKERS_SUPPLY_ROOT=/archive \
  -e MAKERS_SUPPLY_CATALOG_DB=/archive/dist/makers-supply.sqlite \
  -e MAKERS_SUPPLY_STATE_DB=/state/catalog-web.sqlite \
  -e MAKERS_SUPPLY_SECRET_KEY="$CATALOG_SECRET" \
  -e MAKERS_SUPPLY_SECURE_COOKIES=0 \
  -v "$CATALOG_ROOT:/archive:ro" \
  -v "$CATALOG_STATE_VOLUME:/state" \
  "$CATALOG_IMAGE" \
  makers-supply-web create-admin "$CATALOG_ADMIN" "${CATALOG_ADMIN_OPTIONS[@]}"

if docker container inspect "$CATALOG_CONTAINER" >/dev/null 2>&1; then
  echo "Replacing existing $CATALOG_CONTAINER container ..."
  docker rm -f "$CATALOG_CONTAINER" >/dev/null
fi

CATALOG_RUN_OPTIONS=(
  docker run --rm --name "$CATALOG_CONTAINER"
  --read-only
  --tmpfs /tmp:size=64m,mode=1777
  -p "127.0.0.1:$CATALOG_PORT:8000"
  -e MAKERS_SUPPLY_ROOT=/archive
  -e MAKERS_SUPPLY_CATALOG_DB=/archive/dist/makers-supply.sqlite
  -e MAKERS_SUPPLY_STATE_DB=/state/catalog-web.sqlite
  -e "MAKERS_SUPPLY_SECRET_KEY=$CATALOG_SECRET"
  -e MAKERS_SUPPLY_SECURE_COOKIES=0
  -v "$CATALOG_ROOT:/archive:ro"
  -v "$CATALOG_STATE_VOLUME:/state"
)

echo "Catalog UI: http://127.0.0.1:$CATALOG_PORT"
if ((CATALOG_DETACH)); then
  "${CATALOG_RUN_OPTIONS[@]}" -d "$CATALOG_IMAGE"
  echo "Logs: docker logs -f $CATALOG_CONTAINER"
  echo "Stop: docker stop $CATALOG_CONTAINER"
else
  echo "Press Ctrl+C to stop. Accounts, remembered sessions, and lists remain persistent."
  exec "${CATALOG_RUN_OPTIONS[@]}" "$CATALOG_IMAGE"
fi
