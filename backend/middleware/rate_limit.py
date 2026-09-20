"""
Rate limiting middleware - prevents API abuse by limiting requests per API key
"""
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

# In-memory rate limit storage (api_key_id -> {request_count, window_start})
rate_limit_store = {}
RATE_LIMIT = 1000  # requests per hour
WINDOW = 3600  # seconds


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Implement rate limiting: 1000 requests/hour per API key"""

    async def dispatch(self, request: Request, call_next):
        # Only rate limit chat API endpoints
        if not request.url.path.startswith("/api/chat"):
            return await call_next(request)

        # Get API key ID from request state (set by APIKeyAuthMiddleware)
        if not hasattr(request.state, "api_key_id"):
            # If no api_key_id, skip rate limiting (shouldn't happen in practice)
            return await call_next(request)

        api_key_id = request.state.api_key_id
        now = datetime.now(timezone.utc)

        # Initialize or check rate limit
        if api_key_id not in rate_limit_store:
            rate_limit_store[api_key_id] = {
                "count": 1,
                "window_start": now
            }
        else:
            entry = rate_limit_store[api_key_id]
            window_elapsed = (now - entry["window_start"]).total_seconds()

            if window_elapsed < WINDOW:
                # Still in same window
                entry["count"] += 1
                if entry["count"] > RATE_LIMIT:
                    # Return 429 response directly to avoid HTTPException issues
                    return JSONResponse(
                        status_code=429,
                        content={"detail": f"Rate limit exceeded: {RATE_LIMIT} requests per hour"},
                        headers={
                            "X-RateLimit-Limit": str(RATE_LIMIT),
                            "X-RateLimit-Remaining": "0"
                        }
                    )
            else:
                # Window expired, reset
                rate_limit_store[api_key_id] = {
                    "count": 1,
                    "window_start": now
                }

        # Get current limits for response headers
        # Remaining is the count minus current request, but floor at 0
        remaining = max(0, RATE_LIMIT - rate_limit_store[api_key_id]["count"])

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response
