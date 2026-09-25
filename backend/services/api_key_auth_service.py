"""Authenticates a raw API key token against a tenant.

Shared by APIKeyAuthMiddleware (all standard /api routes) and the ecommerce
relay router (which verifies its own bearer token because the middleware
skips /api/ecommerce paths) so the two do not drift out of sync.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import bcrypt

from repositories.mongo_client import MongoConnection

logger = logging.getLogger(__name__)


class APIKeyAuthService:
    """Validates tenant API keys: the current hashed sk_live_/sk_test_ format,
    with a fallback to the legacy plaintext key stored on the tenant record."""

    @staticmethod
    async def authenticate(api_key: str) -> Optional[str]:
        """Return the tenant_id the key belongs to, or None if invalid."""
        db = MongoConnection.get_database()
        tenant_id = None

        if api_key.startswith("sk_live_") or api_key.startswith("sk_test_"):
            api_key_doc = await db["tenant_api_keys"].find_one({
                "active": True,
                "api_key_prefix": api_key[:12],
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

        if not tenant_id:
            tenant_doc = await db["tenants"].find_one({
                "api_key": api_key,
                "status": "active",
            })

            if tenant_doc:
                tenant_id = tenant_doc["tenant_id"]
                api_key_preview = f"{api_key[:12]}...{api_key[-4:]}"
                logger.info(f"✅ Validated legacy API key ({api_key_preview}) for tenant {tenant_id}")
            else:
                api_key_preview = f"{api_key[:8]}..." if len(api_key) > 8 else "***"
                logger.warning(f"❌ API key not found in database ({api_key_preview})")

        return tenant_id
