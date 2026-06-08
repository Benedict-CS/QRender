#!/usr/bin/env bash
# Automated script to pull latest changes and redeploy Docker containers.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo ">>> Pulling latest changes from git..."
git pull

echo ">>> Shutting down existing containers..."
if [[ -f "./docker-run.sh" ]]; then
    ./docker-run.sh down
else
    docker compose down
fi

echo ">>> Rebuilding and starting containers in detached mode..."
if [[ -f "./docker-run.sh" ]]; then
    ./docker-run.sh up -d
else
    docker compose up --build -d
fi

echo ">>> Deployment complete!"
