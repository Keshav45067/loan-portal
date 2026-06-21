"""
STT Service Configuration.
"""
import os
from dotenv import load_dotenv

load_dotenv()

STT_SERVICE_PORT = int(os.getenv("STT_SERVICE_PORT", "50052"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
DEFAULT_ENGINE = os.getenv("DEFAULT_ENGINE", "google")
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "hi-IN")
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "16000"))
