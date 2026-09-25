"""Per-tenant settings unrelated to any specific feature's own data."""

from repositories.mongo_client import MongoConnection


class TenantSettingsService:
    """Business logic for tenant-level settings."""

    @staticmethod
    def _get_db():
        return MongoConnection.get_database()

    @staticmethod
    async def get_ai_enabled(tenant_id: str) -> bool:
        db = TenantSettingsService._get_db()
        tenant = await db["tenants"].find_one({"tenant_id": tenant_id})
        return bool(tenant and tenant.get("ai_enabled", False))

    @staticmethod
    async def set_ai_enabled(tenant_id: str, ai_enabled: bool) -> bool:
        db = TenantSettingsService._get_db()
        await db["tenants"].update_one(
            {"tenant_id": tenant_id},
            {"$set": {"ai_enabled": ai_enabled}}
        )
        return ai_enabled
