#!/usr/bin/env bash
# One-time setup of Navrist on a fresh Ubuntu server (Oracle Cloud Always Free ARM VM, Ubuntu 22.04/24.04).
# Run as the normal "ubuntu" user from the project folder:   bash deploy/server_setup.sh
# It installs Node, Python and cloudflared, builds the site, and creates systemd services that start on boot and restart on a crash.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(id -un)"

sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip build-essential curl git unzip ca-certificates
if ! command -v node >/dev/null || [ "$(node -v | cut -c2-3)" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi
if ! command -v cloudflared >/dev/null; then
  ARCH="$(dpkg --print-architecture)"
  curl -fsSL -o /tmp/cloudflared.deb "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
  sudo dpkg -i /tmp/cloudflared.deb
fi

cd "$APP_DIR"
python3 -m venv venv
./venv/bin/pip install --upgrade pip wheel
# The pinned list was frozen on Windows; install what resolves and report the rest instead of stopping.
./venv/bin/pip install -r requirements.txt || {
  echo "Some pinned packages did not install; retrying one by one and listing the failures."
  while read -r line; do
    [ -z "$line" ] && continue
    ./venv/bin/pip install "$line" >/dev/null 2>&1 || echo "  FAILED: $line"
  done < requirements.txt
}

( cd navrist-web && npm ci && NEXT_DIST_DIR=.next-prod npm run build )

sudo tee /etc/systemd/system/navrist-api.service >/dev/null <<UNIT
[Unit]
Description=Navrist backend (FastAPI, port 8000)
After=network-online.target
[Service]
User=$USER_NAME
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python app.py
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT

sudo tee /etc/systemd/system/navrist-web.service >/dev/null <<UNIT
[Unit]
Description=Navrist web (Next.js, port 3100)
After=navrist-api.service
[Service]
User=$USER_NAME
WorkingDirectory=$APP_DIR/navrist-web
Environment=NEXT_DIST_DIR=.next-prod
ExecStart=/usr/bin/npm run start -- -p 3100
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT

# the tunnel: the same one that serves ai.navrist.com today, with its credentials copied to ~/.cloudflared/
mkdir -p "$HOME/.cloudflared"
if [ -f "$HOME/.cloudflared/tunnel.json" ]; then
  cat > "$HOME/.cloudflared/config.yml" <<CFG
tunnel: navrist
credentials-file: $HOME/.cloudflared/tunnel.json
ingress:
  - hostname: ai.navrist.com
    service: http://localhost:3100
  - service: http_status:404
CFG
  sudo tee /etc/systemd/system/navrist-tunnel.service >/dev/null <<UNIT
[Unit]
Description=Cloudflare Tunnel for ai.navrist.com
After=network-online.target
[Service]
User=$USER_NAME
ExecStart=/usr/bin/cloudflared --no-autoupdate --config $HOME/.cloudflared/config.yml tunnel run navrist
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
else
  echo "NOTE: ~/.cloudflared/tunnel.json is missing, so the tunnel service was not created (see docs/ORACLE_DEPLOY.md step 6)."
fi

sudo systemctl daemon-reload
sudo systemctl enable --now navrist-api navrist-web
[ -f /etc/systemd/system/navrist-tunnel.service ] && sudo systemctl enable --now navrist-tunnel || true
echo "Done. Check:  systemctl status navrist-api navrist-web navrist-tunnel --no-pager"
