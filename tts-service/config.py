"""TTS Service Configuration."""
import os
from dotenv import load_dotenv

load_dotenv()

TTS_SERVICE_PORT = int(os.getenv("TTS_SERVICE_PORT", "50053"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DEFAULT_ENGINE = os.getenv("DEFAULT_ENGINE", "google")
DEFAULT_SAMPLE_RATE = int(os.getenv("DEFAULT_SAMPLE_RATE", "24000"))
