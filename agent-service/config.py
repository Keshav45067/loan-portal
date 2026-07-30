"""
Agent Service Configuration — loads from environment variables.
"""
import os
from dotenv import load_dotenv

load_dotenv()

AGENT_SERVICE_PORT = int(os.getenv("AGENT_SERVICE_PORT", "8090"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Gemini — uses Vertex AI credentials directly (same as llm-service)
USE_VERTEX = os.getenv("USE_VERTEX", "False").lower() in ("true", "1", "yes")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "asia-south1")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-2.5-flash")

# Path to document manifests (from doc-capture service)
MANIFESTS_DIR = os.getenv(
    "MANIFESTS_DIR",
    os.path.join(os.path.dirname(__file__), "..", "doc-capture", "configs", "manifests")
)
