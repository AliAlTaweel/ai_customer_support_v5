"""Test configuration.

config.py validates required env vars at import time, so these must be set
before any test module imports it (directly or transitively).
"""
import os

os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017/test")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("MONGODB_DATABASE_NAME", "ai_customer_support_test")

import pytest


@pytest.fixture
def gmail_env(monkeypatch):
    """Enable the Gmail channel with permissive test settings.

    Individual tests override single values with monkeypatch.setenv.
    """
    monkeypatch.setenv("GMAIL_ENABLED", "true")
    monkeypatch.setenv("GMAIL_TENANT_ID", "T-TEST0001")
    monkeypatch.setenv("GMAIL_ADDRESS", "support@example.com")
    monkeypatch.setenv("GMAIL_DRY_RUN", "false")
    monkeypatch.setenv("GMAIL_ALLOWED_SENDERS", "*")
