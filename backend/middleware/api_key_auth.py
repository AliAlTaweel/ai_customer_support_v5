"""
API Key authentication middleware - validates a tenant API key and injects
tenant_id into request state.
"""
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from services.api_key_auth_service import APIKeyAuthService

logger = logging.getLogger(__name__)


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate requests using a tenant API key, inject tenant_id into request state"""

    async def dispatch(self, request: Request, call_next):
        """Process request with API key authentication"""
        path = request.url.path
        if path in ["/health", "/docs", "/openapi.json"] or not path.startswith("/api"):
            return await call_next(request)

        # Ecommerce relay endpoints verify their own bearer token
        if path.startswith("/api/ecommerce"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"}
            )

        token = auth_header[7:]  # Remove "Bearer " prefix
        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing token"}
            )

        try:
            tenant_id = await APIKeyAuthService.authenticate(token)

            if not tenant_id:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid credentials"}
                )

            request.state.tenant_id = tenant_id

        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication failed"}
            )

        return await call_next(request)
