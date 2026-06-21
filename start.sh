#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Chayan AI — Local Development Startup Script (Services Folder)
# Starts all 8 services + frontend in separate background jobs
# ═══════════════════════════════════════════════════════════

set -e

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$BASE_DIR/.logs"
mkdir -p "$LOG_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
echo -e "${CYAN}           Chayan AI — Starting All Services       ${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
echo ""

# ─── Pre-flight checks ───
echo -e "${YELLOW}🔍 Pre-flight checks...${NC}"

# Check Google credentials
CRED_FILE="$BASE_DIR/../hindi/backend/credentials.json"
if [ ! -f "$CRED_FILE" ]; then
    echo -e "${RED}❌ Google credentials not found at $CRED_FILE${NC}"
    echo "   STT and TTS will fail without Google Cloud credentials."
    exit 1
fi
echo -e "  ✅ Google credentials found"

# Check Gemini API key
if grep -q "PASTE_YOUR" "$BASE_DIR/llm-service/.env" 2>/dev/null; then
    echo -e "${RED}❌ Gemini API key not set in services/llm-service/.env${NC}"
    echo "   Get one from: https://aistudio.google.com/app/apikey"
    echo "   Then edit: $BASE_DIR/llm-service/.env"
    exit 1
fi
echo -e "  ✅ Gemini API key configured"

echo ""

# ─── Function to start a service ───
start_service() {
    local name=$1
    local dir=$2
    local port=$3
    local cmd=$4

    echo -ne "  Starting ${name} (:${port})...."

    cd "$BASE_DIR/$dir"
    eval "$cmd" > "$LOG_DIR/${name}.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$LOG_DIR/${name}.pid"

    # Wait briefly for crash
    sleep 1
    if kill -0 $pid 2>/dev/null; then
        echo -e " ${GREEN}✅ PID $pid${NC}"
    else
        echo -e " ${RED}❌ CRASHED — check $LOG_DIR/${name}.log${NC}"
    fi
}

# ─── Start gRPC Services (order matters for deps) ───
echo -e "${YELLOW}🚀 Starting gRPC services...${NC}"

# 1. Config Registry (no deps)
start_service "config-registry" "config-registry" "50051" \
    "./venv/bin/python -u server.py"

# 2. LLM Service (no deps)
start_service "llm-service" "llm-service" "50054" \
    "./venv/bin/python -u server.py"

# 3. STT Service (no deps)
start_service "stt-service" "stt-service" "50052" \
    "./venv/bin/python -u server.py"

# 4. TTS Service (no deps)
start_service "tts-service" "tts-service" "50053" \
    "./venv/bin/python -u server.py"

# 5. Voice Engine (depends on STT, TTS, LLM, Config)
start_service "voice-engine" "voice-engine" "50056" \
    "./venv/bin/python -u server.py"

# 6. Doc Intelligence (depends on LLM)
start_service "doc-intelligence" "doc-intelligence" "50055" \
    "./venv/bin/python -u server.py"

# 7. App Orchestrator (depends on Config, Doc)
start_service "app-orchestrator" "app-orchestrator" "50057" \
    "./venv/bin/python -u server.py"

echo ""

# ─── Start Gateway ───
echo -e "${YELLOW}🌐 Starting API Gateway...${NC}"
start_service "gateway" "gateway" "8080" \
    "./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080 --log-level info"

echo ""

# ─── Start Frontend ───
echo -e "${YELLOW}🎨 Starting Frontend...${NC}"
cd "$BASE_DIR/frontend"
npm run dev -- -p 3001 > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$LOG_DIR/frontend.pid"
sleep 2
if kill -0 $FRONTEND_PID 2>/dev/null; then
    echo -e "  Frontend (:3001)... ${GREEN}✅ PID $FRONTEND_PID${NC}"
else
    echo -e "  Frontend (:3001)... ${RED}❌ CRASHED${NC}"
fi

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ All services started!${NC}"
echo ""
echo -e "  Frontend:         ${CYAN}http://localhost:3001${NC}"
echo -e "  API Gateway:      ${CYAN}http://localhost:8080${NC}"
echo ""
echo -e "  Logs directory:   ${YELLOW}$LOG_DIR/${NC}"
echo ""
echo -e "  To stop all:      ${YELLOW}bash stop.sh${NC}"
echo -e "  To view logs:     ${YELLOW}tail -f $LOG_DIR/<service>.log${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
