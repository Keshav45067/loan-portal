"""Voice Engine Configuration."""
import os
from dotenv import load_dotenv

load_dotenv()

VOICE_ENGINE_PORT = int(os.getenv("VOICE_ENGINE_PORT", "50056"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
STT_SERVICE_ADDR = os.getenv("STT_SERVICE_ADDR", "localhost:50052")
TTS_SERVICE_ADDR = os.getenv("TTS_SERVICE_ADDR", "localhost:50053")
LLM_SERVICE_ADDR = os.getenv("LLM_SERVICE_ADDR", "localhost:50054")
CONFIG_REGISTRY_ADDR = os.getenv("CONFIG_REGISTRY_ADDR", "localhost:50051")
APP_ORCHESTRATOR_ADDR = os.getenv("APP_ORCHESTRATOR_ADDR", "localhost:50057")
