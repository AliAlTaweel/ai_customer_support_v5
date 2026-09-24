"""
Configuration management for the AI customer support backend
"""
import os
from functools import lru_cache
from typing import Literal
from dotenv import load_dotenv

# Load .env file
load_dotenv()

class Settings:
    """Application settings from environment variables"""

    # Environment
    ENVIRONMENT: Literal["development", "staging", "production"] = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("BACKEND_DEBUG", "true").lower() == "true"

    # MongoDB
    MONGODB_URL: str = os.getenv("MONGODB_URL", "")
    MONGODB_DATABASE_NAME: str = os.getenv("MONGODB_DATABASE_NAME", "ai_customer_support_v5")

    if not MONGODB_URL:
        raise ValueError("MongoDB URL is required. Set MONGODB_URL")

    # Backend
    BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))

    # Gemini AI (auto-reply + embeddings)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_GENERATION_MODEL: str = os.getenv("GEMINI_GENERATION_MODEL", "gemini-3.6-flash")
    GEMINI_EMBEDDING_MODEL: str = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")

    if not GEMINI_API_KEY:
        raise ValueError("Gemini API key is required. Set GEMINI_API_KEY")

    # Shopify integration (optional -- only used if a tenant connects a shop)
    SHOPIFY_API_KEY: str = os.getenv("SHOPIFY_API_KEY", "")
    SHOPIFY_API_SECRET: str = os.getenv("SHOPIFY_API_SECRET", "")

    @property
    def SHOPIFY_TOKEN_ENCRYPTION_KEY(self) -> str:
        # Read dynamically (not frozen at class-definition time like the other
        # Settings attributes above) so tests can monkeypatch this env var
        # regardless of when config.py was first imported in the test session.
        return os.getenv("SHOPIFY_TOKEN_ENCRYPTION_KEY", "")

    # Ecommerce demo shop integration (optional -- single shared tenant)
    ECOMMERCE_SHOP_TENANT_ID: str = os.getenv("ECOMMERCE_SHOP_TENANT_ID", "")
    ECOMMERCE_SHOP_BASE_URL: str = os.getenv("ECOMMERCE_SHOP_BASE_URL", "")
    ECOMMERCE_SHOP_API_SECRET: str = os.getenv("ECOMMERCE_SHOP_API_SECRET", "")

    # Gmail email channel (optional -- single mailbox bound to one tenant)
    @property
    def GMAIL_ENABLED(self) -> bool:
        return os.getenv("GMAIL_ENABLED", "false").lower() == "true"

    @property
    def GMAIL_TENANT_ID(self) -> str:
        return os.getenv("GMAIL_TENANT_ID", "")

    @property
    def GMAIL_ADDRESS(self) -> str:
        return os.getenv("GMAIL_ADDRESS", "").lower()

    @property
    def GMAIL_CLIENT_ID(self) -> str:
        return os.getenv("GMAIL_CLIENT_ID", "")

    @property
    def GMAIL_CLIENT_SECRET(self) -> str:
        return os.getenv("GMAIL_CLIENT_SECRET", "")

    @property
    def GMAIL_REFRESH_TOKEN(self) -> str:
        return os.getenv("GMAIL_REFRESH_TOKEN", "")

    @property
    def GMAIL_POLL_INTERVAL_SECONDS(self) -> int:
        return int(os.getenv("GMAIL_POLL_INTERVAL_SECONDS", "60"))

    @property
    def GMAIL_DRY_RUN(self) -> bool:
        # Defaults to TRUE: a half-configured .env must never send real mail.
        return os.getenv("GMAIL_DRY_RUN", "true").lower() != "false"

    @property
    def GMAIL_ALLOWED_SENDERS(self) -> list[str]:
        # Empty means NOBODY is auto-answered. "*" opens it to everyone.
        raw = os.getenv("GMAIL_ALLOWED_SENDERS", "")
        return [part.strip().lower() for part in raw.split(",") if part.strip()]

    @property
    def GMAIL_MAX_REPLIES_PER_SENDER_HOUR(self) -> int:
        return int(os.getenv("GMAIL_MAX_REPLIES_PER_SENDER_HOUR", "5"))

    @property
    def GMAIL_MAX_SENDS_PER_HOUR(self) -> int:
        return int(os.getenv("GMAIL_MAX_SENDS_PER_HOUR", "50"))

    # CORS - Restrict origins by environment
    if ENVIRONMENT == "production":
        CORS_ORIGINS: list[str] = [
            os.getenv("FRONTEND_URL", "https://app.example.com"),
        ]
    else:
        CORS_ORIGINS: list[str] = [
            "http://localhost:3000",
            "http://localhost:8000",
        ]

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "DEBUG" if DEBUG else "INFO")

@lru_cache()
def get_settings() -> Settings:
    """Get application settings (cached)"""
    return Settings()
