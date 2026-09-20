"""Live order-status lookups from Shopify, gated behind order-number + email verification."""

import re
from typing import Optional
from cryptography.fernet import InvalidToken
from repositories.mongo_client import MongoConnection
from services.shopify_admin_client import ShopifyAdminClient, ShopifyAdminAPIError
from utils.shopify_crypto import decrypt_shopify_token
from utils.logger import logger

ORDER_NUMBER_PATTERN = re.compile(r"^#?\d+$")

ORDER_STATUS_QUERY = """
query getOrderByName($query: String!) {
  orders(first: 1, query: $query) {
    edges {
      node {
        displayFulfillmentStatus
        customer { email }
        fulfillments(first: 1) {
          trackingInfo { url }
        }
      }
    }
  }
}
"""


class ShopifyOrderService:
    @staticmethod
    async def get_order_status(tenant_id: str, order_number: str, email: str) -> dict:
        if not ORDER_NUMBER_PATTERN.match(order_number or ""):
            # Malformed/malicious order_number (e.g. containing Shopify search
            # DSL wildcards or field prefixes) is treated as a verification
            # failure, not a distinct error, so it can't be used as an oracle.
            return {"verified": False}

        if not (email or "").strip():
            # An empty/whitespace-only email can never be a valid second
            # factor. Without this, an order whose Shopify customer record
            # also has an empty email would satisfy "" == "" and leak
            # fulfillment status + tracking with no real verification.
            # Checked before querying Shopify at all.
            return {"verified": False}

        db = MongoConnection.get_database()
        tenant = await db["tenants"].find_one({"tenant_id": tenant_id})

        shop_domain = tenant.get("shopify_shop_domain") if tenant else None
        encrypted_token = tenant.get("shopify_access_token") if tenant else None
        if not shop_domain or not encrypted_token:
            logger.error(f"Tenant {tenant_id} has no Shopify connection for order lookup")
            return {"error": True}

        try:
            access_token = decrypt_shopify_token(encrypted_token)
            data = await ShopifyAdminClient.graphql_query(
                shop_domain=shop_domain,
                access_token=access_token,
                query=ORDER_STATUS_QUERY,
                variables={"query": f"name:{order_number}"},
            )
        except (ShopifyAdminAPIError, InvalidToken) as e:
            logger.error(f"Shopify order lookup failed for tenant {tenant_id}: {e}")
            return {"error": True}

        edges = data.get("orders", {}).get("edges", [])
        if not edges:
            return {"verified": False}

        order = edges[0]["node"]
        order_email = (order.get("customer") or {}).get("email", "")
        if order_email.strip().lower() != email.strip().lower():
            return {"verified": False}

        tracking_url: Optional[str] = None
        fulfillments = order.get("fulfillments") or []
        if fulfillments:
            tracking_info = fulfillments[0].get("trackingInfo") or []
            if tracking_info:
                tracking_url = tracking_info[0].get("url")

        return {
            "verified": True,
            "status": order.get("displayFulfillmentStatus"),
            "tracking_url": tracking_url,
        }
