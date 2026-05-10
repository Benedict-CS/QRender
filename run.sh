#!/usr/bin/env bash
# Local dev launcher (not Docker — for Docker use ./docker-run.sh).
# Usage:
#   ./run.sh           → local uvicorn (uses .venv + .env if present)
#   ./run.sh dev       → same
#   ./run.sh docker    → delegates to ./docker-run.sh
#   ./run.sh install   → create .venv and pip install -e .

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

MODE="${1:-dev}"

run_dev() {
  if [[ -f "$ROOT/.venv/bin/activate" ]]; then
    # shellcheck source=/dev/null
    source "$ROOT/.venv/bin/activate"
  fi

  if [[ -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$ROOT/.env"
    set +a
  fi

  local port="${PORT:-8000}"
  echo "Starting uvicorn on 0.0.0.0:${port} (set PORT in .env to change)"
  exec python -m uvicorn app.main:app --reload --host 0.0.0.0 --port "${port}"
}

run_docker() {
  exec "$ROOT/docker-run.sh" run
}

run_install() {
  if [[ ! -d "$ROOT/.venv" ]]; then
    python3 -m venv "$ROOT/.venv"
  fi
  # shellcheck source=/dev/null
  source "$ROOT/.venv/bin/activate"
  python -m pip install -U pip
  pip install -e "$ROOT"
  echo "Done. Run: ./run.sh"
}

case "$MODE" in
  dev)
    run_dev
    ;;
  docker)
    run_docker
    ;;
  install)
    run_install
    ;;
  -h | --help | help)
    cat <<EOF
QRender launcher

  ./run.sh              Local server (.venv optional, loads .env)
  ./run.sh dev          Same as above
  ./run.sh docker       Same as ./docker-run.sh (Docker build + up)
  ./run.sh install      Create .venv and pip install -e .

  For containers use:   ./docker-run.sh  (see ./docker-run.sh help)

Environment (see .env.example):
  PORT                  HTTP port for ./run.sh dev (default 8000)
  ADMIN_SECRET, PUBLIC_BASE_URL, ...
EOF
    ;;
  *)
    echo "Unknown command: $MODE" >&2
    echo "Use: ./run.sh help" >&2
    exit 1
    ;;
esac
