#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Chayan AI — Stop All Services
# ═══════════════════════════════════════════════════════════

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$BASE_DIR/.logs"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

echo "🛑 Stopping all Chayan AI services..."

# 1. Stop via PID files
for pidfile in "$LOG_DIR"/*.pid; do
    if [ -f "$pidfile" ]; then
        name=$(basename "$pidfile" .pid)
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null
            echo -e "  Stopped ${name} (PID $pid) ${GREEN}✅${NC}"
        else
            echo -e "  ${name} already stopped"
        fi
        rm -f "$pidfile"
    fi
done

# 2. Aggressive zombie sweep by port
echo ""
echo -e "${YELLOW}🧹 Sweeping for rogue zombie processes on service ports...${NC}"

PORTS=(50051 50052 50053 50054 50055 50056 50057 8080 3001)

for port in "${PORTS[@]}"; do
    pids=$(lsof -t -i:$port 2>/dev/null)
    if [ -n "$pids" ]; then
        pid_list=$(echo $pids | tr '\n' ' ')
        echo -e "  ${RED}Found rogue processes on port $port (PIDs: $pid_list). Killing...${NC}"
        kill -9 $pids 2>/dev/null
    fi
done

echo ""
echo -e "${GREEN}✅ All services stopped and ports cleared.${NC}"
