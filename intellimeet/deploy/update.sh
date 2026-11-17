#!/usr/bin/env bash
# Pull the latest code from GitHub, rebuild and restart:  bash deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."
git pull
.venv/bin/pip install -q -e '.[local,gemini]'
(cd frontend && npm ci --silent && npm run build)
sudo systemctl restart intellimeet
echo "Updated and restarted."
