#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Augmen — Systemd Service Auto-Setup Script
# Must be run with sudo/root privileges on the VM
# ═══════════════════════════════════════════════════════════

set -e

# Verify root privileges
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root/sudo: sudo bash setup.sh"
  exit 1
fi

BASE_DIR="/var/www/augmen/testing-services"
USER_NAME="${SUDO_USER:-$(logname 2>/dev/null || echo "ubuntu")}"

# ─── 1. Setup gRPC Services ───
SERVICES=("config-registry" "llm-service" "stt-service" "tts-service" "voice-engine" "doc-intelligence" "app-orchestrator")
PORTS=(50051 50054 50052 50053 50056 50055 50057)

echo "⚙️ Creating systemd service files for gRPC services..."

for i in "${!SERVICES[@]}"; do
    SERVICE="${SERVICES[$i]}"
    PORT="${PORTS[$i]}"
    SERVICE_FILE="/etc/systemd/system/augmen-${SERVICE}.service"
    
    echo "  Generating $SERVICE_FILE..."
    
    cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=Augmen ${SERVICE} gRPC Service
After=network.target

[Service]
User=${USER_NAME}
WorkingDirectory=${BASE_DIR}/${SERVICE}
Environment=PYTHONPATH=${BASE_DIR}
Environment=GOOGLE_APPLICATION_CREDENTIALS=${BASE_DIR}/../hindi/backend/credentials.json
ExecStart=${BASE_DIR}/${SERVICE}/venv/bin/python -u server.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
done

# ─── 2. Setup Gateway Service (Gunicorn/Uvicorn) ───
GATEWAY_FILE="/etc/systemd/system/augmen-gateway.service"
echo "⚙️ Creating systemd service file for API Gateway..."

# Make sure gunicorn is installed
if [ -f "${BASE_DIR}/gateway/venv/bin/pip" ]; then
    echo "  Ensuring Gunicorn is installed in gateway venv..."
    ${BASE_DIR}/gateway/venv/bin/pip install -q gunicorn uvicorn
fi

cat <<EOF > "$GATEWAY_FILE"
[Unit]
Description=Augmen API Gateway Service (Gunicorn/Uvicorn)
After=network.target

[Service]
User=${USER_NAME}
WorkingDirectory=${BASE_DIR}/gateway
Environment=PYTHONPATH=${BASE_DIR}
Environment=GOOGLE_APPLICATION_CREDENTIALS=${BASE_DIR}/../hindi/backend/credentials.json
ExecStart=${BASE_DIR}/gateway/venv/bin/gunicorn main:app \
          -w 4 \
          -k uvicorn.workers.UvicornWorker \
          -b 127.0.0.1:8080 \
          --access-logfile - \
          --error-logfile -
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ─── 3. Reload and Enable Services ───
echo "🔄 Reloading systemd daemon..."
systemctl daemon-reload

echo "🚀 Enabling and starting services..."
for SERVICE in "${SERVICES[@]}"; do
    systemctl enable "augmen-${SERVICE}"
    systemctl start "augmen-${SERVICE}"
    echo "  Started augmen-${SERVICE} ✅"
done

systemctl enable augmen-gateway
systemctl start augmen-gateway
echo "  Started augmen-gateway ✅"

echo ""
echo "🎉 Systemd services successfully registered and started!"
echo "   You can check their status using: systemctl status augmen-*"
