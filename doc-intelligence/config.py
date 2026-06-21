"""Doc Intelligence Configuration."""
import os
from dotenv import load_dotenv

load_dotenv()

DOC_INTELLIGENCE_PORT = int(os.getenv("DOC_INTELLIGENCE_PORT", "50055"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
GCS_BUCKET = os.getenv("GCS_BUCKET", "chayan-documents")
LLM_SERVICE_ADDR = os.getenv("LLM_SERVICE_ADDR", "localhost:50054")
CONFIG_REGISTRY_ADDR = os.getenv("CONFIG_REGISTRY_ADDR", "localhost:50051")
SUREPASS_API_KEY = os.getenv("SUREPASS_API_KEY", "")

from pathlib import Path
STORAGE_ROOT = os.getenv("LOCAL_STORAGE_ROOT")
if STORAGE_ROOT is None:
    STORAGE_ROOT = Path.home() / ".my_app_storage"
else:
    STORAGE_ROOT = Path(STORAGE_ROOT)

PHOTOS_DIR = STORAGE_ROOT / "photos"
JSON_DIR = STORAGE_ROOT / "json"

PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
JSON_DIR.mkdir(parents=True, exist_ok=True)

