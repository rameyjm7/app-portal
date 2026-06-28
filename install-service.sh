#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="app-portal"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
RUN_USER="${SUDO_USER:-${USER}}"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ "${EUID}" -ne 0 ]]; then
  exec sudo --preserve-env=PYTHON_BIN bash "$0" "$@"
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found; this installer requires systemd." >&2
  exit 1
fi

if [[ ! -f "${APP_DIR}/server.py" ]]; then
  echo "server.py not found in ${APP_DIR}" >&2
  exit 1
fi

cat > "${UNIT_FILE}" <<UNIT
[Unit]
Description=Local App Portal
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${PYTHON_BIN} ${APP_DIR}/server.py --host 0.0.0.0 --port 80
Restart=on-failure
RestartSec=2
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"
systemctl restart "${SERVICE_NAME}.service"

echo "${SERVICE_NAME} installed and started."
echo "Status: systemctl status ${SERVICE_NAME}.service"
echo "Logs:   journalctl -u ${SERVICE_NAME}.service -f"
