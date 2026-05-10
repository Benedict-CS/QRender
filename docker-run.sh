#!/usr/bin/env bash
# Build and run QRender with Docker Compose (see Dockerfile + docker-compose.yml).
# Requires Docker Engine with Compose v2: `docker compose`.
#
# Usage:
#   ./docker-run.sh              # build + up (foreground)
#   ./docker-run.sh up -d        # build + detached
#   ./docker-run.sh build        # build image only
#   ./docker-run.sh down         # stop containers
#   ./docker-run.sh logs         # follow logs
#   ./docker-run.sh ps           # status

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    cat <<'EOF' >&2
docker: command not found — Docker Engine is not installed (or not in PATH).

Ubuntu / Debian (official repo, summary):
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${VERSION_CODENAME:-jammy}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

After install, the "docker" group exists. Then (optional, avoid sudo for docker):
  sudo usermod -aG docker "$USER"
  # log out and back in

Then verify:  docker compose version

Without Docker you can still run the app locally:  ./run.sh

One-shot Docker install (needs sudo password once):  ./install-docker.sh
EOF
    exit 127
  fi
  if ! docker compose version >/dev/null 2>&1; then
    echo "docker is installed but 'docker compose' failed. Install the Compose plugin (docker-compose-plugin)." >&2
    exit 127
  fi
}

warn_env() {
  if [[ ! -f "$ROOT/.env" ]]; then
    echo "Tip: copy .env.example to .env and set ADMIN_SECRET and PUBLIC_BASE_URL." >&2
  fi
}

CMD="${1:-run}"
if [[ $# -ge 1 ]]; then
  shift
fi

case "$CMD" in
  help | -h | --help)
    cat <<'EOF'
QRender — Docker

  ./docker-run.sh           docker compose up --build (foreground)
  ./docker-run.sh run       same
  ./docker-run.sh up -d     build + run in background
  ./docker-run.sh build     docker compose build
  ./docker-run.sh down      stop/remove containers
  ./docker-run.sh logs      follow logs
  ./docker-run.sh ps        list services

Host ./data is mounted to /app/data (SQLite + QR previews).
Compose reads .env in this directory for PORT, PUBLIC_BASE_URL, ADMIN_SECRET.
EOF
    exit 0
    ;;
esac

require_docker

case "$CMD" in
  run | up)
    warn_env
    exec docker compose up --build "$@"
    ;;
  build)
    exec docker compose build "$@"
    ;;
  down)
    exec docker compose down "$@"
    ;;
  logs)
    exec docker compose logs -f "$@"
    ;;
  ps)
    exec docker compose ps "$@"
    ;;
  *)
    echo "Unknown command: $CMD" >&2
    echo "Run: ./docker-run.sh help" >&2
    exit 1
    ;;
esac
