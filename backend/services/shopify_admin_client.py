"""Shared HTTP client for Shopify's Admin GraphQL API."""

import asyncio
import aiohttp
from utils.logger import logger

ADMIN_API_VERSION = "2024-01"
REQUEST_TIMEOUT_SECONDS = 10


class ShopifyAdminAPIError(Exception):
    """Raised when a Shopify Admin API call fails or returns GraphQL errors."""
    pass


class ShopifyAdminClient:
    @staticmethod
    async def graphql_query(shop_domain: str, access_token: str, query: str, variables: dict) -> dict:
        url = f"https://{shop_domain}/admin/api/{ADMIN_API_VERSION}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }
        payload = {"query": query, "variables": variables}
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"Shopify Admin API returned {resp.status} for {shop_domain}: {body}")
                        raise ShopifyAdminAPIError(f"Shopify Admin API returned status {resp.status}")

                    body = await resp.json()
                    if "errors" in body:
                        logger.error(f"Shopify Admin API GraphQL errors for {shop_domain}: {body['errors']}")
                        raise ShopifyAdminAPIError(f"Shopify Admin API GraphQL errors: {body['errors']}")

                    return body["data"]
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            logger.error(f"Shopify Admin API request failed for {shop_domain}: {e}")
            raise ShopifyAdminAPIError(f"Shopify Admin API request failed: {e}") from e
