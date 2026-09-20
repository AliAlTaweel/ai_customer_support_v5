"""Logging configuration and utilities."""

import logging
import sys
from typing import Optional
from contextvars import ContextVar
from datetime import datetime


# Context variables for tracking
request_id_context: ContextVar[str] = ContextVar("request_id", default="unknown")
user_context: ContextVar[Optional[str]] = ContextVar("user", default=None)


class ContextFilter(logging.Filter):
    """Add request context to log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Add context variables to the log record."""
        record.request_id = request_id_context.get()
        record.user = user_context.get() or "anonymous"
        return True


def setup_logger(name: str = __name__, level: int = logging.INFO) -> logging.Logger:
    """
    Configure a logger with context tracking and formatted output.

    Args:
        name: Logger name (typically __name__)
        level: Logging level (default: INFO)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Console handler with formatting
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    # Formatter with context information
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - [%(request_id)s] [%(user)s] - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)

    # Add context filter
    context_filter = ContextFilter()
    handler.addFilter(context_filter)

    logger.addHandler(handler)

    return logger


# Global logger instance
logger = setup_logger(__name__)


def set_request_id(request_id: str) -> None:
    """Set the request ID for the current context."""
    request_id_context.set(request_id)


def set_user(user: Optional[str]) -> None:
    """Set the user for the current context."""
    user_context.set(user)


def get_request_id() -> str:
    """Get the current request ID."""
    return request_id_context.get()


def get_user() -> Optional[str]:
    """Get the current user."""
    return user_context.get()
