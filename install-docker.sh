#!/usr/bin/env bash
# Official Docker Engine install (Ubuntu/Debian via get.docker.com). Requires sudo password once.
# After: log out/in, then ./docker-run.sh

set -euo pipefail

if ! command -v curl >/dev/null 2>&1; then
  echo "Install curl first: sudo apt-get install -y curl" >&2
  exit 1
fi

echo "Installing Docker Engine via https://get.docker.com (official script)..."
curl -fsSL https://get.docker.com | sudo sh

sudo systemctl enable --now docker

sudo usermod -aG docker "${SUDO_USER:-$USER}"

echo ""
echo "Docker installed. Verify:"
sudo docker compose version
echo ""
echo "Next: log out and back in (or reboot) so group 'docker' applies."
echo "Then without sudo:  docker compose version"
echo "Run QRender:         cd $(dirname "$0") && ./docker-run.sh"
