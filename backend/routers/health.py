"""Health check and root endpoints for the API."""

from fastapi import APIRouter
from datetime import datetime
from models import HealthResponse
from config import get_settings

# Create router
router = APIRouter()

settings = get_settings()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint"""
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(),
        message="Backend is running"
    )


@router.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Luxe AI Customer Support Backend",
        "version": "0.1.0",
        "environment": settings.ENVIRONMENT,
        "docs": "/docs"
    }
