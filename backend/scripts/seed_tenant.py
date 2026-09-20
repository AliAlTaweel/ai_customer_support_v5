"""Create a tenant and issue an API key for it.

There's no tenant-management dashboard in this project (that lives in the
full platform this AI engine was extracted from) -- this script is the
replacement: it writes a tenant record directly to Mongo and mints an API
key via APIKeyService, the same code path the full platform's tenant API
used.

Usage:
    python -m scripts.seed_tenant --name "Acme Inc" --email admin@acme.com
"""
import argparse
import asyncio
import uuid
from datetime import datetime, timezone

from config import get_settings
from repositories.mongo_client import MongoConnection
from services.api_key_service import APIKeyService


async def seed_tenant(name: str, organization_email: str) -> None:
    settings = get_settings()
    await MongoConnection.connect(settings.MONGODB_URL, settings.MONGODB_DATABASE_NAME)
    db = MongoConnection.get_database()

    tenant_id = f"T-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc)

    await db["tenants"].insert_one({
        "tenant_id": tenant_id,
        "name": name,
        "organization_email": organization_email,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    })

    key_info = await APIKeyService.create_key(tenant_id, environment="live", name="Default Key")

    await MongoConnection.disconnect()

    print(f"Tenant created: {tenant_id} ({name})")
    print(f"API key (copy this now, it will not be shown again): {key_info['api_key']}")
    print()
    print("Use it as: Authorization: Bearer " + key_info["api_key"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a tenant and issue an API key")
    parser.add_argument("--name", required=True, help="Tenant display name")
    parser.add_argument("--email", required=True, help="Tenant organization email")
    args = parser.parse_args()

    asyncio.run(seed_tenant(args.name, args.email))


if __name__ == "__main__":
    main()
