"""
Shared structured logging library for all Chayan services.

Provides JSON-formatted logging with req_id correlation, service name,
and latency tracking. Every log line includes the req_id for end-to-end tracing.

Usage:
    from shared.logging.logger import get_logger, extract_req_id

    logger = get_logger("llm-service")
    logger.info("Processing request", req_id="abc123", extra_field="value")
"""

import logging
import json
import time
import uuid
import sys
import socket
from datetime import datetime, timezone
from typing import Optional
from contextvars import ContextVar

# Context variable for req_id propagation within async contexts
_req_id_var: ContextVar[str] = ContextVar("req_id", default="")


def set_req_id(req_id: str):
    """Set the current request ID in the context."""
    _req_id_var.set(req_id)


def get_req_id() -> str:
    """Get the current request ID from the context."""
    return _req_id_var.get()


def generate_req_id() -> str:
    """Generate a new unique request ID."""
    return str(uuid.uuid4())[:8]


def extract_req_id(context) -> str:
    """
    Extract req_id from gRPC metadata context.

    Args:
        context: gRPC servicer context with invocation_metadata()

    Returns:
        req_id string, generates one if not found
    """
    req_id = ""
    try:
        metadata = dict(context.invocation_metadata())
        req_id = metadata.get("x-request-id", "")
    except Exception:
        pass

    if not req_id:
        req_id = generate_req_id()

    set_req_id(req_id)
    return req_id


class StructuredFormatter(logging.Formatter):
    """JSON structured log formatter with consistent fields across all services."""

    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "req_id": getattr(record, "req_id", get_req_id()) or "-",
            "message": record.getMessage(),
        }

        # Add optional fields if present
        for field in ["session_id", "node_id", "method", "latency_ms",
                      "document_type", "scheme_id", "application_id",
                      "engine", "language", "model", "error", "details",
                      "raw_output"]:
            value = getattr(record, field, None)
            if value is not None:
                log_entry[field] = value

        # Add exception info if present
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class ServiceLogger:
    """
    Structured logger for a specific service.

    Wraps Python's logging module with structured JSON output and
    automatic req_id injection from context.
    """

    def __init__(self, service_name: str, level: int = logging.INFO):
        self._logger = logging.getLogger(f"chayan.{service_name}")
        self._logger.setLevel(level)
        self._logger.propagate = False

        # Remove existing handlers
        self._logger.handlers.clear()

        # Add structured JSON handler to stdout
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredFormatter(service_name))
        self._logger.addHandler(handler)

        self.service_name = service_name

    def _log(self, level: int, message: str, **kwargs):
        """Internal log method that injects context fields."""
        # Always include req_id from context if not explicitly provided
        if "req_id" not in kwargs:
            kwargs["req_id"] = get_req_id()

        # Extract standard logging arguments
        exc_info = kwargs.pop("exc_info", None)
        stack_info = kwargs.pop("stack_info", False)

        # Create log record with extra fields
        extra = {k: v for k, v in kwargs.items()}
        self._logger.log(level, message, exc_info=exc_info, stack_info=stack_info, extra=extra)

    def info(self, message: str, **kwargs):
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log(logging.ERROR, message, **kwargs)

    def debug(self, message: str, **kwargs):
        self._log(logging.DEBUG, message, **kwargs)

    def critical(self, message: str, **kwargs):
        self._log(logging.CRITICAL, message, **kwargs)


class LatencyTracker:
    """
    Context manager for tracking operation latency.

    Usage:
        with LatencyTracker() as t:
            do_work()
        logger.info("Done", latency_ms=t.elapsed_ms)
    """

    def __init__(self):
        self.start_time = None
        self.elapsed_ms = 0

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = round((time.perf_counter() - self.start_time) * 1000, 2)


def get_logger(service_name: str, level: int = logging.INFO) -> ServiceLogger:
    """
    Get a structured logger for the given service.

    Args:
        service_name: Name of the service (e.g. "llm-service", "voice-engine")
        level: Logging level (default INFO)

    Returns:
        ServiceLogger instance
    """
    return ServiceLogger(service_name, level)
