"""
FastAPI application factory - AI customer support engine (chat + knowledge base)
"""
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import get_settings
from database import Database
from middleware import APIKeyAuthMiddleware, RateLimitMiddleware
from routers import health, chat, knowledge_base
from routers.ecommerce_chat import router as ecommerce_chat_router
from utils.logging_setup import setup_logging, setup_chat_logger, setup_ai_logger, print_log_info
from contextlib import asynccontextmanager

# Configure comprehensive logging
logger = setup_logging("main")
chat_logger = setup_chat_logger()
ai_logger = setup_ai_logger()
print_log_info()
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Application startup and shutdown events"""
    logger.info("🚀 Starting AI Customer Support Backend")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Debug: {settings.DEBUG}")
    logger.info(f"MongoDB Database: {settings.MONGODB_DATABASE_NAME}")
    try:
        await Database.connect()
        await Database.init_chat_collections()
        logger.info("✓ Chat collections initialized")
        await Database.init_knowledge_base_collections()
        logger.info("✓ Knowledge base collections initialized")
    except Exception as e:
        logger.error(f"✗ Failed to connect to database: {e}")
        raise

    yield

    logger.info("🛑 Shutting down backend")
    await Database.disconnect()
    logger.info("✓ Backend shutdown complete")


def create_app() -> FastAPI:
    """Create and configure FastAPI application"""
    app = FastAPI(
        title="AI Customer Support API",
        description="AI chat + knowledge base engine (multi-tenant)",
        version="0.1.0",
        lifespan=_lifespan
    )

    # Add middleware in order (last added is first executed)
    # CORS must be added last to execute first and handle preflight requests
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(APIKeyAuthMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        """Add unique request ID to all requests"""
        request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(f"[{request_id}] {request.method} {request.url.path} - {response.status_code}")
        return response

    # Register routers
    app.include_router(health)
    app.include_router(chat)
    app.include_router(knowledge_base)
    app.include_router(ecommerce_chat_router)

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Global exception handler for unhandled errors"""
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )

    return app


# Create the application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.BACKEND_PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )
