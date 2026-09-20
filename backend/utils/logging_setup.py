"""Centralized logging setup for backend services."""

import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime

# Create logs directory if it doesn't exist
LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Log file paths
MAIN_LOG_FILE = LOGS_DIR / "backend.log"
ERROR_LOG_FILE = LOGS_DIR / "backend_errors.log"
CHAT_LOG_FILE = LOGS_DIR / "chat_messages.log"
AI_LOG_FILE = LOGS_DIR / "ai_responses.log"

# Color codes for console output
class ColoredFormatter(logging.Formatter):
    """Formatter that adds color to console output."""

    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'

    def format(self, record):
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"
        return super().format(record)


def setup_logging(logger_name: str = None) -> logging.Logger:
    """
    Set up logging with both file and console output.

    Args:
        logger_name: Name of the logger (defaults to root logger if None)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(logger_name)

    # Avoid adding duplicate handlers
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # File handler for main log (all levels)
    file_handler = RotatingFileHandler(
        MAIN_LOG_FILE,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)

    # File handler for errors only
    error_handler = RotatingFileHandler(
        ERROR_LOG_FILE,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = ColoredFormatter(
        '[%(levelname)s] %(message)s'
    )
    console_handler.setFormatter(console_formatter)

    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)
    logger.addHandler(console_handler)

    return logger


def setup_chat_logger() -> logging.Logger:
    """Set up dedicated logger for chat/message operations."""
    logger = logging.getLogger('chat')

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    handler = RotatingFileHandler(
        CHAT_LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=5
    )
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '[%(asctime)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def setup_ai_logger() -> logging.Logger:
    """Set up dedicated logger for AI operations."""
    logger = logging.getLogger('ai')

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    handler = RotatingFileHandler(
        AI_LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=5
    )
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '[%(asctime)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


# Print log file locations on startup
def print_log_info():
    """Print log file locations for reference."""
    print("\n" + "="*60)
    print("📝 LOG FILES CREATED")
    print("="*60)
    print(f"Main Log:       {MAIN_LOG_FILE}")
    print(f"Error Log:      {ERROR_LOG_FILE}")
    print(f"Chat Log:       {CHAT_LOG_FILE}")
    print(f"AI Log:         {AI_LOG_FILE}")
    print("="*60)
    print("View logs with: tail -f logs/<filename>.log")
    print("="*60 + "\n")
