"""Live order lookups from the ecommerce_shop_01 demo shop.

Unlike the Shopify order tool, no order-number/email verification is needed
here: the shop only calls our chat endpoint after it has already verified
the customer's identity via its own Clerk session, and passes us that
customer's id directly. We trust it the same way we trust conv_doc's
customer_identifier for any other channel.
"""

from config import get_settings
from services.ecommerce_shop_client import EcommerceShopClient, EcommerceShopAPIError
from utils.logger import logger


class EcommerceOrderService:
    @staticmethod
    async def get_customer_orders(tenant_id: str, customer_id: str) -> dict:
        settings = get_settings()
        if (
            tenant_id != settings.ECOMMERCE_SHOP_TENANT_ID
            or not settings.ECOMMERCE_SHOP_BASE_URL
            or not settings.ECOMMERCE_SHOP_API_SECRET
        ):
            logger.error(f"Tenant {tenant_id} has no ecommerce shop connection configured")
            return {"error": True}

        if not customer_id:
            return {"found": False}

        try:
            data = await EcommerceShopClient.get(
                base_url=settings.ECOMMERCE_SHOP_BASE_URL,
                path="/api/external/orders",
                api_secret=settings.ECOMMERCE_SHOP_API_SECRET,
                params={"customerId": customer_id},
            )
        except EcommerceShopAPIError as e:
            logger.error(f"Ecommerce order lookup failed for tenant {tenant_id}: {e}")
            return {"error": True}

        orders = data.get("orders", [])
        if not orders:
            return {"found": False}

        return {"found": True, "orders": orders}
