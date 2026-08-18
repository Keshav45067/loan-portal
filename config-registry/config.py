"""Config Registry Configuration."""
import os
from dotenv import load_dotenv

load_dotenv()

CONFIG_REGISTRY_PORT = int(os.getenv("CONFIG_REGISTRY_PORT", "50051"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_TTL_SECONDS = int(os.getenv("REDIS_TTL_SECONDS", "3600"))
CONFIG_DIR = os.getenv("CONFIG_DIR", os.path.join(os.path.dirname(__file__), "configs"))
