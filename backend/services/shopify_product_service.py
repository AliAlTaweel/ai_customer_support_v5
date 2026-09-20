"""Live product data lookups from Shopify. No identity verification — product data
isn't customer-specific. Never extend this to return customer- or order-specific data."""

from cryptography.fernet import InvalidToken
from repositories.mongo_client import MongoConnection
from services.shopify_admin_client import ShopifyAdminClient, ShopifyAdminAPIError
from utils.shopify_crypto import decrypt_shopify_token
from utils.logger import logger

# Characters with special meaning in Shopify's search DSL (wildcards, field
# prefixes, quoting) are stripped from free-text product queries so a crafted
# query can't be used to shift which product gets returned to the customer.
_SEARCH_DSL_SPECIAL_CHARS = str.maketrans("", "", '*:"')

PRODUCT_SEARCH_QUERY = """
query searchProducts($query: String!) {
  products(first: 1, query: $query) {
    edges {
      node {
        title
        description
        variants(first: 1) {
          edges {
            node {
              price
              availableForSale
            }
          }
        }
      }
    }
  }
}
"""


class ShopifyProductService:
    @staticmethod
    async def get_product_info(tenant_id: str, product_query: str) -> dict:
        db = MongoConnection.get_database()
        tenant = await db["tenants"].find_one({"tenant_id": tenant_id})

        shop_domain = tenant.get("shopify_shop_domain") if tenant else None
        encrypted_token = tenant.get("shopify_access_token") if tenant else None
        if not shop_domain or not encrypted_token:
            logger.error(f"Tenant {tenant_id} has no Shopify connection for product lookup")
            return {"error": True}

        sanitized_query = (product_query or "").translate(_SEARCH_DSL_SPECIAL_CHARS)

        try:
            access_token = decrypt_shopify_token(encrypted_token)
            data = await ShopifyAdminClient.graphql_query(
                shop_domain=shop_domain,
                access_token=access_token,
                query=PRODUCT_SEARCH_QUERY,
                variables={"query": f"title:*{sanitized_query}*"},
            )
        except (ShopifyAdminAPIError, InvalidToken) as e:
            logger.error(f"Shopify product lookup failed for tenant {tenant_id}: {e}")
            return {"error": True}

        edges = data.get("products", {}).get("edges", [])
        if not edges:
            return {"found": False}

        product = edges[0]["node"]
        variant_edges = product.get("variants", {}).get("edges", [])
        variant = variant_edges[0]["node"] if variant_edges else {}

        return {
            "found": True,
            "title": product.get("title"),
            "price": variant.get("price"),
            "description": product.get("description"),
            "available": variant.get("availableForSale", False),
        }
