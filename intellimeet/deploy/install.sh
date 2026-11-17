#!/usr/bin/env bash
# One-time setup of IntelliMeet on an Ubuntu 22.04/24.04 server (x86-64), e.g. an Azure VM.
#
#   git clone https://github.com/Kanika0004/IntelliMeet.git && cd IntelliMeet
#   sudo bash deploy/install.sh your-name.centralindia.cloudapp.azure.com
#
# It installs Chrome, a virtual screen + virtual speaker, Python/Node dependencies, builds the
# website, creates a systemd service and puts Caddy (automatic HTTPS) in front of it.
set -euo pipefail

DOMAIN="${1:-}"
if [[ -z "$DOMAIN" ]]; then
  echo "Usage: sudo bash deploy/install.sh <your domain, e.g. intellimeet.centralindia.cloudapp.azure.com>"; exit 1
fi
if [[ $EUID -ne 0 ]]; then echo "Run with sudo."; exit 1; fi
RUN_USER="${SUDO_USER:-$(logname)}"
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "==> Installing IntelliMeet from $APP_DIR for user $RUN_USER at https://$DOMAIN"

read -rp "Gemini API key (from aistudio.google.com): " GEMINI_KEY
read -rsp "Password for the remote screen used to sign the bot in to Google: " SCREEN_PW; echo

export DEBIAN_FRONTEND=noninteractive
echo "==> System packages"
apt-get update -q
apt-get install -y -q ca-certificates curl gnupg git python3 python3-venv python3-pip ffmpeg \
  xvfb pulseaudio pulseaudio-utils x11vnc novnc websockify libportaudio2 fonts-noto fonts-noto-color-emoji \
  debian-keyring debian-archive-keyring apt-transport-https

echo "==> Node.js 22"
if ! node -v 2>/dev/null | grep -q "^v2[2-9]"; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y -q nodejs
fi

echo "==> Google Chrome"
if ! command -v google-chrome >/dev/null; then
  curl -fsSL -o /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  apt-get install -y -q /tmp/chrome.deb
fi

echo "==> Caddy (HTTPS)"
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy
fi

echo "==> Swap (helps on 4 GB machines)"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

echo "==> Python environment and website build"
sudo -u "$RUN_USER" bash -c "cd '$APP_DIR' && python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -e '.[local,gemini]'"
sudo -u "$RUN_USER" bash -c "cd '$APP_DIR/frontend' && npm ci --silent && npm run build"

echo "==> Configuration (.env)"
if [[ ! -f "$APP_DIR/.env" ]]; then
  cat > "$APP_DIR/.env" <<ENV
# Hosted IntelliMeet - edit and then: sudo systemctl restart intellimeet
AUTH_ENABLED=true
ALLOW_SIGNUP=true
HOST=127.0.0.1
PORT=8000
DATA_DIR=./data
HEADLESS=false
AUDIO_SOURCE=loopback
BOT_DISPLAY_NAME=IntelliMeet Bot
RECORDING_DURATION=1800
TRANSCRIBER=local
LOCAL_WHISPER_MODEL=base
LOCAL_WHISPER_DEVICE=cpu
ANALYZER=gemini
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_API_KEY=$GEMINI_KEY
REMOTE_SCREEN_URL=https://$DOMAIN/screen/vnc.html?path=screen/websockify&autoconnect=true&resize=scale
ENV
  chown "$RUN_USER" "$APP_DIR/.env"; chmod 600 "$APP_DIR/.env"
fi
chmod +x "$APP_DIR/deploy/start.sh"

echo "==> Service"
cat > /etc/systemd/system/intellimeet.service <<UNIT
[Unit]
Description=IntelliMeet (web app, meeting bot, virtual screen and speaker)
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/deploy/start.sh
Restart=always
RestartSec=5
KillMode=control-group
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now intellimeet

echo "==> HTTPS"
HASH="$(caddy hash-password --plaintext "$SCREEN_PW")"
cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
	encode gzip
	# Remote view of the server's virtual screen (only for signing the bot in to Google)
	handle_path /screen/* {
		basic_auth {
			admin $HASH
		}
		reverse_proxy 127.0.0.1:6080
	}
	handle {
		reverse_proxy 127.0.0.1:8000
	}
}
CADDY
systemctl reload caddy || systemctl restart caddy

echo
echo "Done. Open https://$DOMAIN and create the first account - it becomes the administrator."
echo "Logs: sudo journalctl -u intellimeet -f"
