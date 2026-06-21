"""
LLM Service Configuration — loads from environment variables.
"""
import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
LLM_SERVICE_PORT = int(os.getenv("LLM_SERVICE_PORT", "50054"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-2.5-flash")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
USE_VERTEX = os.getenv("USE_VERTEX", "False").lower() in ("true", "1", "yes")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "asia-south1")

# Model aliases for convenience
MODEL_ALIASES = {
    "flash": "gemini-2.5-flash",
    "pro": "gemini-2.5-pro",
    "flash-lite": "gemini-2.0-flash-lite",
}
