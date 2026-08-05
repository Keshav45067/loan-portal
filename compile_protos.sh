#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Augmen — Protobuf Recompile and Service Restart Script
# Must be run with sudo/root privileges on the VM
# ═══════════════════════════════════════════════════════════

set -e

# Verify root privileges
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root/sudo: sudo bash compile_protos.sh"
  exit 1
fi

BASE_DIR="/var/www/augmen/testing-services"

echo "🔨 Compiling protobuf stubs..."
SERVICES=("agent-service" "doc-capture" "config-registry" "llm-service" "stt-service" "tts-service" "voice-engine" "doc-intelligence" "app-orchestrator" "gateway")

for SERVICE in "${SERVICES[@]}"; do
    if [ -f "${BASE_DIR}/${SERVICE}/Makefile" ]; then
        echo "  Compiling protos for $SERVICE..."
        cd "${BASE_DIR}/${SERVICE}"
	venv/bin/pip install -r requirements.txt
        make proto
    fi
done

cd "${BASE_DIR}"

echo "🔄 Restarting Augmen systemd services..."
for SERVICE in "${SERVICES[@]}"; do
    if systemctl list-units --all --type=service | grep -q "augmen-${SERVICE}.service"; then
        systemctl restart "augmen-${SERVICE}"
        echo "  Restarted augmen-${SERVICE} ✅"
    fi
done

echo "🎉 Protobuf compilation and service restarts complete!"
