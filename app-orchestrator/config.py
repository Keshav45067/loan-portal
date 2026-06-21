"""App Orchestrator Configuration."""
import os
from dotenv import load_dotenv

load_dotenv()

APP_ORCHESTRATOR_PORT = int(os.getenv("APP_ORCHESTRATOR_PORT", "50057"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/chayan")
CONFIG_REGISTRY_ADDR = os.getenv("CONFIG_REGISTRY_ADDR", "localhost:50051")
DOC_INTELLIGENCE_ADDR = os.getenv("DOC_INTELLIGENCE_ADDR", "localhost:50055")
VOICE_ENGINE_ADDR = os.getenv("VOICE_ENGINE_ADDR", "localhost:50056")
