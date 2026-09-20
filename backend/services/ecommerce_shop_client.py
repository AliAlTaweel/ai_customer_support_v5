"""Shared HTTP client for the ecommerce_shop_01 demo shop's external data API."""

import asyncio
import aiohttp
from utils.logger import logger

REQUEST_TIMEOUT_SECONDS = 10


class EcommerceShopAPIError(Exception):
    """Raised when a call to the ecommerce shop's external API fails."""
    pass


class EcommerceShopClient:
    @staticmethod
    async def get(base_url: str, path: str, api_secret: str, params: dict) -> dict:
        url = f"{base_url.rstrip('/')}{path}"
        headers = {"X-API-Secret": api_secret}
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"Ecommerce shop API returned {resp.status} for {url}: {body}")
                        raise EcommerceShopAPIError(f"Ecommerce shop API returned status {resp.status}")
                    return await resp.json()
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            logger.error(f"Ecommerce shop API request failed for {url}: {e}")
            raise EcommerceShopAPIError(f"Ecommerce shop API request failed: {e}") from e
