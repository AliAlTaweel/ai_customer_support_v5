"""API routers for the application.

This module exports all routers for easy import in the main FastAPI app.
"""

from routers.health import router as health
from routers.chat import router as chat
from routers.knowledge_base import router as knowledge_base

__all__ = ["health", "chat", "knowledge_base"]
