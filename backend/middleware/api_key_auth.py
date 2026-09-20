"""
API Key authentication middleware - validates a tenant API key and injects
tenant_id into request state.
"""
import bcrypt
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from repositories.mongo_client import MongoConnection
from datetime import datetime, timezone

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
            tenant_id = await self._validate_api_key(token)

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

    async def _validate_api_key(self, api_key: str) -> str:
        """Validate API key and return tenant_id"""
        db = MongoConnection.get_database()
        tenant_id = None

        # New format: sk_live_... or sk_test_... (hashed, see services/api_key_service.py)
        if api_key.startswith("sk_live_") or api_key.startswith("sk_test_"):
            api_key_doc = await db["tenant_api_keys"].find_one({
                "active": True,
                "api_key_prefix": api_key[:12]
            })

            if api_key_doc:
                api_key_bytes = api_key.encode()
                stored_hash = api_key_doc.get("api_key_hash", b"")

                if isinstance(stored_hash, str):
                    stored_hash = stored_hash.encode()

                if bcrypt.checkpw(api_key_bytes, stored_hash):
                    await db["tenant_api_keys"].update_one(
                        {"_id": api_key_doc["_id"]},
                        {"$set": {"last_used_at": datetime.now(timezone.utc)}}
                    )
                    tenant_id = api_key_doc["tenant_id"]
                    api_key_preview = f"{api_key[:12]}...{api_key[-4:]}"
                    logger.info(f"✅ Validated API key ({api_key_preview}) for tenant {tenant_id}")

        # Fallback: plain API key stored directly on the tenant record
        if not tenant_id:
            tenant_doc = await db["tenants"].find_one({
                "api_key": api_key,
                "status": "active"
            })

            if tenant_doc:
                tenant_id = tenant_doc["tenant_id"]
                api_key_preview = f"{api_key[:12]}...{api_key[-4:]}"
                logger.info(f"✅ Validated legacy API key ({api_key_preview}) for tenant {tenant_id}")
            else:
                api_key_preview = f"{api_key[:8]}..." if len(api_key) > 8 else "***"
                logger.warning(f"❌ API key not found in database ({api_key_preview})")

        return tenant_id
