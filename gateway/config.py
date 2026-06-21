"""Gateway Configuration."""
import os
from dotenv import load_dotenv

load_dotenv()

GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "8080"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# JWT Config — lightweight, only for client ↔ gateway auth
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))

# GCP
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "augmen-docs")

# gRPC service addresses
LLM_SERVICE_ADDR = os.getenv("LLM_SERVICE_ADDR", "localhost:50054")
STT_SERVICE_ADDR = os.getenv("STT_SERVICE_ADDR", "localhost:50052")
TTS_SERVICE_ADDR = os.getenv("TTS_SERVICE_ADDR", "localhost:50053")
CONFIG_REGISTRY_ADDR = os.getenv("CONFIG_REGISTRY_ADDR", "localhost:50051")
DOC_INTELLIGENCE_ADDR = os.getenv("DOC_INTELLIGENCE_ADDR", "localhost:50055")
VOICE_ENGINE_ADDR = os.getenv("VOICE_ENGINE_ADDR", "localhost:50056")
APP_ORCHESTRATOR_ADDR = os.getenv("APP_ORCHESTRATOR_ADDR", "localhost:50057")
