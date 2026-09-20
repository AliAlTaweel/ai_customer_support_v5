"""Service for managing tenant API keys."""

import secrets
import logging
from datetime import datetime, timezone
import bcrypt
from typing import Optional, List, Dict
from repositories.mongo_client import MongoConnection

logger = logging.getLogger(__name__)


class APIKeyService:
    """Manage API key generation, validation, and lifecycle."""

    PREFIX_LENGTH = 12
    KEY_LENGTH = 32
    PRODUCTION_PREFIX = "sk_live_"
    TEST_PREFIX = "sk_test_"

    @staticmethod
    def generate_key(environment: str = "live") -> str:
        """Generate a new API key with proper format.

        Args:
            environment: "live" or "test"

        Returns:
            Full API key (e.g., "sk_live_abc123xyz...")
        """
        prefix = APIKeyService.PRODUCTION_PREFIX if environment == "live" else APIKeyService.TEST_PREFIX
        random_part = secrets.token_urlsafe(APIKeyService.KEY_LENGTH)
        return f"{prefix}{random_part}"

    @staticmethod
    def _hash_key(api_key: str) -> str:
        """Hash API key using bcrypt."""
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(api_key.encode('utf-8'), salt)
        return hashed.decode('utf-8')

    @staticmethod
    async def create_key(
        tenant_id: str,
        environment: str = "live",
        name: str = None
    ) -> Dict[str, str]:
        """Create a new API key for a tenant.

        Args:
            tenant_id: The tenant ID
            environment: "live" or "test"
            name: Optional human-readable name for the key

        Returns:
            Dict with full_key (display once) and key_id
        """
        try:
            # Generate key
            full_key = APIKeyService.generate_key(environment)
            key_prefix = full_key[:APIKeyService.PREFIX_LENGTH]
            key_hash = APIKeyService._hash_key(full_key)

            # Create document
            from uuid import uuid4
            key_id = f"key_{uuid4().hex[:12]}"

            key_doc = {
                "api_key_id": key_id,
                "tenant_id": tenant_id,
                "api_key_hash": key_hash,
                "api_key_prefix": key_prefix,
                "environment": environment,
                "name": name or f"{environment.capitalize()} Key",
                "created_at": datetime.now(timezone.utc),
                "active": True,
                "last_used_at": None,
                "usage_count": 0
            }

            db = MongoConnection.get_database()
            result = await db["tenant_api_keys"].insert_one(key_doc)

            logger.info(f"✓ API key created: {key_id} for tenant {tenant_id}")

            return {
                "key_id": key_id,
                "api_key": full_key,  # Show once
                "prefix": key_prefix,
                "environment": environment,
                "created_at": key_doc["created_at"].isoformat()
            }

        except Exception as e:
            logger.error(f"Error creating API key: {e}")
            raise

    @staticmethod
    async def revoke_key(key_id: str, tenant_id: str) -> bool:
        """Revoke an API key.

        Args:
            key_id: The key ID to revoke
            tenant_id: The tenant ID (for validation)

        Returns:
            True if revoked, False if not found
        """
        try:
            db = MongoConnection.get_database()
            result = await db["tenant_api_keys"].update_one(
                {"api_key_id": key_id, "tenant_id": tenant_id},
                {"$set": {"active": False, "revoked_at": datetime.now(timezone.utc)}}
            )

            if result.modified_count > 0:
                logger.info(f"✓ API key revoked: {key_id}")
                return True

            return False

        except Exception as e:
            logger.error(f"Error revoking API key: {e}")
            raise

    @staticmethod
    async def list_keys(tenant_id: str, active_only: bool = True) -> List[Dict]:
        """List all API keys for a tenant.

        Args:
            tenant_id: The tenant ID
            active_only: If True, only return active keys

        Returns:
            List of key documents (without hashes)
        """
        try:
            db = MongoConnection.get_database()
            query = {"tenant_id": tenant_id}

            if active_only:
                query["active"] = True

            keys = await db["tenant_api_keys"].find(query).to_list(length=None)

            # Remove sensitive data
            for key in keys:
                key.pop("api_key_hash", None)
                if "_id" in key:
                    key["_id"] = str(key["_id"])
                # Format dates
                if "created_at" in key and hasattr(key["created_at"], "isoformat"):
                    key["created_at"] = key["created_at"].isoformat()
                if "last_used_at" in key and key["last_used_at"] and hasattr(key["last_used_at"], "isoformat"):
                    key["last_used_at"] = key["last_used_at"].isoformat()
                if "revoked_at" in key and key.get("revoked_at") and hasattr(key["revoked_at"], "isoformat"):
                    key["revoked_at"] = key["revoked_at"].isoformat()

            return keys

        except Exception as e:
            logger.error(f"Error listing API keys: {e}")
            raise

    @staticmethod
    async def get_key_info(key_id: str, tenant_id: str) -> Optional[Dict]:
        """Get information about a specific API key.

        Args:
            key_id: The key ID
            tenant_id: The tenant ID (for validation)

        Returns:
            Key document (without hash) or None if not found
        """
        try:
            db = MongoConnection.get_database()
            key = await db["tenant_api_keys"].find_one({
                "api_key_id": key_id,
                "tenant_id": tenant_id
            })

            if not key:
                return None

            # Remove sensitive data
            key.pop("api_key_hash", None)
            if "_id" in key:
                key["_id"] = str(key["_id"])

            # Format dates
            if "created_at" in key and hasattr(key["created_at"], "isoformat"):
                key["created_at"] = key["created_at"].isoformat()
            if "last_used_at" in key and key["last_used_at"] and hasattr(key["last_used_at"], "isoformat"):
                key["last_used_at"] = key["last_used_at"].isoformat()

            return key

        except Exception as e:
            logger.error(f"Error fetching API key info: {e}")
            raise
