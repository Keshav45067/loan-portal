"""Doc-Capture Service Configuration."""
import os
from dotenv import load_dotenv

load_dotenv()

DOC_CAPTURE_PORT = int(os.getenv("DOC_CAPTURE_PORT", "50058"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:nImr1327!@34.14.191.93:5432/smart-mudraa")
LLM_SERVICE_ADDR = os.getenv("LLM_SERVICE_ADDR", "localhost:50054")
OCR_SERVICE_ADDR = os.getenv("OCR_SERVICE_ADDR", "localhost:50059")
APP_ORCHESTRATOR_ADDR = os.getenv("APP_ORCHESTRATOR_ADDR", "localhost:50057")

# Cache TTL
CONFIG_CACHE_TTL_SECONDS = int(os.getenv("CONFIG_CACHE_TTL_SECONDS", "3600"))
