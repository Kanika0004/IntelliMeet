#!/usr/bin/env bash
# Starts everything IntelliMeet needs on a Linux server, then the web app itself.
#   Xvfb       - a virtual screen (:99) so Chrome can run with a real window
#   PulseAudio - a virtual speaker "meet"; Chrome plays the meeting into it and the
#                recorder captures its monitor (loopback) - no sound card needed
#   x11vnc + websockify/noVNC - lets the admin see that screen in a browser (bot sign-in)
set -euo pipefail
cd "$(dirname "$0")/.."

export DISPLAY=:99
export XDG_RUNTIME_DIR="$PWD/data/runtime"
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"

Xvfb :99 -screen 0 1366x768x24 -nolisten tcp &
sleep 1

pulseaudio --kill 2>/dev/null || true
pulseaudio --daemonize=yes --exit-idle-time=-1 --disallow-exit
for i in 1 2 3 4 5; do pactl info >/dev/null 2>&1 && break; sleep 1; done
pactl load-module module-null-sink sink_name=meet sink_properties=device.description=MeetAudio >/dev/null
pactl set-default-sink meet

# Remote screen for signing the bot in to Google (localhost only; Caddy adds a password + HTTPS).
x11vnc -display :99 -forever -shared -nopw -localhost -rfbport 5900 -quiet -bg -o "$PWD/data/x11vnc.log"
NOVNC_WEB=/usr/share/novnc
websockify --web "$NOVNC_WEB" 127.0.0.1:6080 127.0.0.1:5900 >/dev/null 2>&1 &

exec .venv/bin/intellimeet serve
